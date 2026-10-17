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
    locate_in_catalog,
    require_file,
    resolve,
)
from chartbook.resolve import resolve_catalog_path as _resolve_catalog_path
from chartbook.utils import is_glob_pattern


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


#: Where :func:`scratch` puts throwaway files, relative to the pipeline root.
SCRATCH_DIR = Path("_data") / "_scratch"


def scratch(project_dir: Optional[Union[str, Path]] = None) -> Path:
    """Get the current pipeline's directory for throwaway files.

    Use it for intermediates that nothing else depends on: a partial
    download, a cache between two steps, a file you only want to look at.

    >>> from chartbook import data
    >>> tmp = data.scratch() / "raw_download.csv"  # doctest: +SKIP

    The directory is ``_data/_scratch/`` inside the pipeline, created on
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
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    directory = find_manifest_dir(*start_dirs) / SCRATCH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return directory


def _get_dataframe_docs_info_from_catalog(
    catalog_path: Path,
    pipeline: str,
    dataframe: str,
) -> tuple:
    """Look up docs info for a dataframe inside a catalog manifest.

    :param catalog_path: Path to the catalog's ``chartbook.toml``.
    :type catalog_path: Path
    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :returns: Tuple of (doc_mode, doc_value, pipeline_base_dir) where doc_mode
        is ``"path"`` or ``"str"``, doc_value is the path string or inline
        content, and pipeline_base_dir is the base directory of the pipeline.
    :rtype: tuple[str, str, Path]
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    from chartbook.manifest import load_manifest

    manifest = load_manifest(base_dir=catalog_path.parent)

    pipeline_key = locate_in_catalog(manifest, pipeline)

    pipeline_manifest = manifest["pipelines"][pipeline_key]
    available_dataframes = list(pipeline_manifest.get("dataframes", {}).keys())
    if dataframe not in pipeline_manifest.get("dataframes", {}):
        raise KeyError(
            f"Dataframe {dataframe!r} not found in pipeline {pipeline_key!r}. "
            f"Available dataframes: {available_dataframes}"
        )

    df_manifest = pipeline_manifest["dataframes"][dataframe]
    doc_mode = df_manifest["_doc_mode"]
    doc_value = df_manifest["_doc_value"]
    pipeline_base_dir = Path(pipeline_manifest["base_dir"])

    return doc_mode, doc_value, pipeline_base_dir


def get_data_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the resolved path to a dataframe's parquet file, through a catalog.

    For glob patterns (e.g., ``**/*.parquet``), returns a ``Path`` containing
    the glob pattern characters.

    :func:`path` supersedes this inside a pipeline: ``data.path("name")`` for
    its own dataframes, and ``data.path("pipeline:name")`` for the pinned
    copy of a declared dependency's. This remains the way to find a
    dataframe through a catalog, from a notebook that belongs to no
    pipeline, say. It gives the file in the pipeline's newest snapshot in
    the store (in a pipeline that declares it, its pin); with no snapshot,
    the file in the folder the catalog lists, with a
    :class:`~chartbook.resolve.WorkingVersionWarning`.

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
    :returns: The resolved path to the parquet file (may contain glob characters).
    :rtype: Path
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path)
    return require_file(location, f"Dataframe {dataframe!r}")


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
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    resolved_catalog = _resolve_catalog_path(catalog_path)
    doc_mode, doc_value, pipeline_base_dir = _get_dataframe_docs_info_from_catalog(
        resolved_catalog, pipeline, dataframe
    )
    if doc_mode == "path":
        return (pipeline_base_dir / doc_value).resolve()
    else:  # doc_mode == "str"
        return (pipeline_base_dir / "chartbook.toml").resolve()


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
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    resolved_catalog = _resolve_catalog_path(catalog_path)
    doc_mode, doc_value, pipeline_base_dir = _get_dataframe_docs_info_from_catalog(
        resolved_catalog, pipeline, dataframe
    )
    if doc_mode == "path":
        doc_path = (pipeline_base_dir / doc_value).resolve()
        return doc_path.read_text()
    else:  # doc_mode == "str"
        return doc_value


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
    are in is loaded from where its manifest says it is: a parquet file, or
    a table or query in one of its ``[sources]``, in which case the source's
    engine runs it and the frame is fetched whole when it is collected. A
    dataframe of another pipeline is loaded from the copy that
    ``chartbook.lock`` pins, so it does not change until you run
    ``chartbook update``:

    >>> from chartbook import data
    >>> mine = data.load("term_premium")  # doctest: +SKIP
    >>> theirs = data.load("yield_curve:fed_yield_curve")  # doctest: +SKIP

    The other pipeline is declared in ``[dependencies]`` and pinned with
    ``chartbook pin``, or by the first read: one declared and not pinned
    is pinned then, to its newest snapshot, and stderr says so. One not
    declared is read from its newest snapshot with an
    :class:`~chartbook.resolve.UnrecordedReadWarning`, and one with no
    snapshot from its folder with a
    :class:`~chartbook.resolve.WorkingVersionWarning`. Under
    ``chartbook run``'s ``build`` (``CHARTBOOK_BATCH=1``) only a pin is
    read. Outside any pipeline, the newest snapshot is read and nothing is
    said.

    **Through a catalog**, with a pipeline and a dataframe. This reads by
    the same rules: its pin, in a pipeline that declares it; otherwise its
    newest snapshot in the store; with no snapshot, the file in the folder
    the catalog lists, as it is now, with a
    :class:`~chartbook.resolve.WorkingVersionWarning`:

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
        alias for ``"polars"``).  Glob patterns in a dataframe's ``path`` only
        support ``"polars"`` (LazyFrame).
    :type format: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory, to load through.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :param pipeline: The pipeline to load from through a catalog — a bare
        name (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: Optional[str]
    :param project_dir: Where to look for the current pipeline when loading
        by reference, as for :func:`path`.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The loaded dataframe in the requested format.
    :rtype: pandas.DataFrame or polars.DataFrame or polars.LazyFrame
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises DependencyNotDeclaredError: If a reference names a pipeline that
        ``[dependencies]`` does not declare, in a batch run, or when it has
        neither a snapshot nor a folder here.
    :raises AssetNotPinnedError: If another pipeline's dataframe has no
        copy to read: no pin in a batch run, and otherwise no snapshot and
        no folder here.
    :raises CatalogNotConfiguredError: If a catalog is needed and none is
        configured, and the store has no snapshot of the pipeline.
    :raises KeyError: If the pipeline or dataframe is in neither the store
        nor the catalog.
    :raises TypeError: If the arguments are neither one reference nor a
        pipeline and a dataframe.
    :raises ValueError: If *format* is not one of the supported values, or if
        a glob path is used with a non-LazyFrame format.

    **Examples**

    Load as a Polars eager DataFrame:

    >>> df = data.load("yield_curve:fed_yield_curve",
    ...               format="polars_eager")  # doctest: +SKIP

    Load as a pandas DataFrame, through a catalog:

    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="pandas",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP
    """
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
        location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path)
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
        start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
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
    if not isinstance(location, FileLocation):
        # A table or a query in a source: the backend binds it now, runs it
        # when the frame is collected, Arrow comes back, Polars wraps it.
        from chartbook.backends import backend_for

        frame = backend_for(location).scan(location)
        if format in ("polars", "polars-lazyframe"):
            return frame
        if format == "polars_eager":
            return frame.collect()
        if format == "pandas":
            return frame.collect().to_pandas()
        raise ValueError(
            f"Invalid format: {format!r}. Must be 'polars', 'polars_eager', "
            f"'pandas', or 'polars-lazyframe'."
        )
    file_path = location.path
    _is_glob = is_glob_pattern(file_path)

    if format == "pandas":
        if _is_glob:
            raise ValueError(
                "Glob patterns in a dataframe's path only support format='polars' "
                "(LazyFrame). Use data.load(..., format='polars') and call .collect() "
                "to materialize, then .to_pandas() if needed."
            )
        import pandas as pd

        return pd.read_parquet(file_path)
    elif format == "polars":
        import polars as pl

        return pl.scan_parquet(file_path, hive_partitioning=True)
    elif format == "polars_eager":
        if _is_glob:
            raise ValueError(
                "Glob patterns in a dataframe's path only support format='polars' "
                "(LazyFrame). Use data.load(..., format='polars') and call .collect() "
                "to materialize."
            )
        import polars as pl

        return pl.read_parquet(file_path, hive_partitioning=True)
    elif format == "polars-lazyframe":
        import warnings

        import polars as pl

        warnings.warn(
            "format='polars-lazyframe' is deprecated. Use format='polars' instead "
            "(polars format now returns LazyFrame by default).",
            DeprecationWarning,
            stacklevel=2,
        )
        return pl.scan_parquet(file_path, hive_partitioning=True)
    else:
        raise ValueError(
            f"Invalid format: {format!r}. Must be 'polars', 'polars_eager', "
            f"'pandas', or 'polars-lazyframe'."
        )


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

    A file is ``read_parquet('…')``, which DuckDB reads as a table. A table
    in a source is its quoted identifier. A query in a source is the query,
    in parentheses, so it stands where a table would. Paste it into SQL you
    run with :func:`connect`, or with your own tooling.

    :param reference: The dataframe: a name of this pipeline's, or
        ``pipeline:name`` for a pinned one of another's.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises AssetNotPinnedError: If another pipeline's dataframe has no
        pinned copy.
    """
    from chartbook.backends import backend_for

    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    asset = _assets.parse(reference, kind="dataframe")
    location = resolve(asset, start_dirs=start_dirs)
    backend = backend_for(location)
    if location.kind != "file":
        backend.check_pin(location)
    return backend.ref(location)


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
    files. ChartBook never parses or rewrites the SQL; what is between the
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
    from chartbook.backends import DuckDBBackend, backend_for, open_backend

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
    replacements = {}
    for text, location in locations.items():
        if location.kind == "file":
            replacements[text] = backend_for(location).ref(location)
        else:
            # A pinned version is checked to be of the table pinned, as a load checks it
            engine.check_pin(location)
            replacements[text] = engine.ref(location)
    # In one pass, so that nothing put in is read again as a reference
    query = _REFERENCE_IN_SQL.sub(lambda found: replacements.get(found.group(1), found.group(0)), query)
    query = query.replace(_LITERAL_OPEN, "{").replace(_LITERAL_CLOSE, "}")
    pinned = [location for location in locations.values() if getattr(location, "version", None) is not None]
    # Checked again when the frame is collected, as a load's is
    return engine.sql(query, recheck=pinned) if pinned else engine.sql(query)


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

