"""
Shared pytest fixtures for integration testing.
"""

import pytest

from tests.fixtures import (
    create_catalog_project,
    create_invalid_toml_project,
    create_pipeline_project,
)


def pytest_configure(config):
    """On Windows, make each test's folder in a short one of this run's own.

    pytest's own, ``%TEMP%\\pytest-of-<user>\\pytest-<n>\\``, takes 64
    characters before a test's name, and a catalog's version pages under
    it go past the 260 Windows takes: a test then fails for where it ran.
    A run given ``--basetemp`` keeps it, and so does a worker of a run on
    several cores, which is handed its folder by the run that started it.
    What the folder is, and why also where long paths are on:
    :func:`tests.fixtures.short_base_folder`.
    """
    import os

    from tests.fixtures import short_base_folder

    if config.option.basetemp:
        return
    folder = short_base_folder(os.name == "nt", bool(getattr(config.option, "numprocesses", None)))
    if folder is not None:
        config.option.basetemp = folder


@pytest.fixture(scope="session", autouse=True)
def _keep_the_run_out_of_the_real_store(tmp_path_factory):
    """Scratch folders for the whole run: what a fixture of a class, a module or the session is given.

    Such a fixture is set up before the test's own scratch folders are
    (:func:`_keep_out_of_the_real_store`), and ran with this machine's own
    settings and cache until this was here: one of them builds a site.
    """
    from tests.fixtures import kept_out_of_home, remove_tree

    scratch = tmp_path_factory.mktemp("chartbook_home_of_the_run")
    with kept_out_of_home(scratch):
        yield
    try:
        remove_tree(scratch)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _keep_out_of_the_real_store(tmp_path_factory):
    """Point the store, the caches and the settings at scratch folders of its own, for every test.

    What is set, and why, is in :func:`tests.fixtures.kept_out_of_home`. It
    is set by that block's own patches, and not by the ``monkeypatch`` a test
    asks for: a test that calls ``monkeypatch.undo()`` half-way undoes what
    it set itself, and is kept out to its end. While the two were one,
    ``undo()`` took all of this away as well, and the rest of such a test ran
    with this machine's own cache and settings (found on 2026-11-17: a
    folder made in ``~/.chartbook/cache`` at every run).
    """
    from tests.fixtures import kept_out_of_home, remove_tree

    scratch = tmp_path_factory.mktemp("chartbook_home")
    with kept_out_of_home(scratch):
        yield
    # The scratch store and caches go with their test. Found on CI on
    # 2026-10-21: the suite's temporary files, every test's stores and sites
    # kept until the end, filled the runner's disk at 99% of the run
    try:
        remove_tree(scratch)  # the store's read-only objects too, which Windows does not remove alone
    except OSError:
        pass


@pytest.fixture
def pipeline_project(tmp_path):
    """Creates and returns path to a complete pipeline project.

    The project includes:
    - chartbook.toml with valid pipeline config
    - src/ directory with a source file
    - docs_src/ directory with index.md
    - _data/{pipeline_id}/ with parquet files
    - 1 dataframe with 1 chart
    """
    return create_pipeline_project(
        tmp_path / "pipeline_project",
        pipeline_id="test_pipeline",
        pipeline_name="Test Pipeline",
        include_dataframes=True,
        include_charts=True,
    )


@pytest.fixture
def pipeline_project_with_notes(tmp_path):
    """Creates a pipeline project that includes notes."""
    return create_pipeline_project(
        tmp_path / "pipeline_with_notes",
        pipeline_id="notes_pipeline",
        pipeline_name="Pipeline With Notes",
        include_dataframes=True,
        include_charts=True,
        include_notes=True,
    )


@pytest.fixture
def pipeline_project_multi_dataframes(tmp_path):
    """Creates a pipeline project with multiple dataframes and charts."""
    return create_pipeline_project(
        tmp_path / "multi_df_project",
        pipeline_id="multi_df",
        pipeline_name="Multi Dataframe Pipeline",
        include_dataframes=True,
        include_charts=True,
        dataframe_count=2,
        charts_per_dataframe=2,
    )


@pytest.fixture
def catalog_project(tmp_path):
    """Creates and returns path to a catalog with 2 pipelines."""
    from tests.fixtures import publish_catalog
    return publish_catalog(create_catalog_project(
        tmp_path / "catalog_project",
        pipeline_ids=["pipeline_a", "pipeline_b"],
    ))


@pytest.fixture
def catalog_project_platform_paths(tmp_path):
    """Creates a catalog project using platform-specific path dicts."""
    from tests.fixtures import publish_catalog
    return publish_catalog(create_catalog_project(
        tmp_path / "catalog_platform",
        pipeline_ids=["pipeline_x", "pipeline_y"],
        use_platform_paths=True,
    ))


@pytest.fixture
def catalog_project_inline_docs(tmp_path):
    """Creates a catalog project with inline docs (dataframe_docs_str)."""
    from tests.fixtures import publish_catalog
    return publish_catalog(create_catalog_project(
        tmp_path / "catalog_inline_docs",
        pipeline_ids=["pipeline_inline"],
        use_inline_docs=True,
    ))


@pytest.fixture
def catalog_project_glob(tmp_path):
    """Creates a catalog project with glob/hive-partitioned parquet data."""
    from tests.fixtures import publish_catalog
    return publish_catalog(create_catalog_project(
        tmp_path / "catalog_glob",
        pipeline_ids=["pipeline_glob"],
        use_glob_paths=True,
    ))


@pytest.fixture
def pipeline_project_with_site_dir(tmp_path):
    """Pipeline project with site_dir inside docs_src/."""
    return create_pipeline_project(
        tmp_path / "pipeline_site",
        pipeline_id="site_test",
        pipeline_name="Site Dir Test",
        include_site_dir=True,
        site_dir_in_docs_src=True,
    )


@pytest.fixture
def pipeline_project_with_site_dir_top_level(tmp_path):
    """Pipeline project with site_dir at top level (backward compat)."""
    return create_pipeline_project(
        tmp_path / "pipeline_site_top",
        pipeline_id="site_top_test",
        pipeline_name="Site Dir Top Level Test",
        include_site_dir=True,
        site_dir_in_docs_src=False,
    )


@pytest.fixture
def invalid_project_missing_file(tmp_path):
    """Creates a project without chartbook.toml."""
    return create_invalid_toml_project(tmp_path / "missing_file", "missing_file")


@pytest.fixture
def invalid_project_invalid_type(tmp_path):
    """Creates a project with invalid config type."""
    return create_invalid_toml_project(tmp_path / "invalid_type", "invalid_type")


@pytest.fixture
def invalid_project_v1_format(tmp_path):
    """Creates a project with an old v1-format chartbook.toml."""
    return create_invalid_toml_project(tmp_path / "v1_format", "v1_format")


@pytest.fixture
def invalid_project_type_conflict(tmp_path):
    """Creates a project whose explicit type contradicts its structure."""
    return create_invalid_toml_project(tmp_path / "type_conflict", "type_conflict")
