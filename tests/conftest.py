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
    """On Windows with long paths off, make each test's folder in a short one of this run's own.

    pytest's own, ``%TEMP%\\pytest-of-<user>\\pytest-<n>\\``, takes 64
    characters before a test's name, and a catalog's version pages under
    it go past the 260 Windows takes: a test then fails for where it ran.
    A run given ``--basetemp`` keeps it.
    """
    import os
    import tempfile

    from chartbook.store import long_paths_enabled

    if os.name != "nt" or config.option.basetemp or long_paths_enabled():
        return
    config.option.basetemp = tempfile.mkdtemp(prefix="cbt-")


@pytest.fixture(autouse=True)
def _keep_out_of_the_real_store(tmp_path_factory, monkeypatch):
    """Point the store and the git cache at scratch directories, for every test.

    Both are per user and live under ``~/.chartbook``. A test that pins,
    or a command it runs in a subprocess, must never write there. Setting
    the two environment variables is what a user would do to move them, so
    code that asks for "this user's store" gets a scratch one. Tests of
    where the default is clear the variables themselves.
    """
    scratch = tmp_path_factory.mktemp("chartbook_home")
    monkeypatch.setenv("CHARTBOOK_STORE", str(scratch / "store"))
    monkeypatch.setenv("CHARTBOOK_GIT_CACHE", str(scratch / "git"))
    monkeypatch.setenv("CHARTBOOK_CACHE", str(scratch / "cache"))
    # The organization's settings file, read where the user's is silent:
    # a real one on this machine must not reach a test
    monkeypatch.setenv("CHARTBOOK_SYSTEM_SETTINGS", str(scratch / "system-settings.toml"))
    # A test is interactive unless it says otherwise, even under `chartbook run`
    monkeypatch.delenv("CHARTBOOK_BATCH", raising=False)
    # Every folder a test builds is trusted to run, as the user's own would
    # be once trusted, and CI's own `CI=true` does not reach a test: the
    # tests of trust itself (tests/test_trust.py) clear the first and set
    # the second themselves
    monkeypatch.setenv("CHARTBOOK_TRUST", "all")
    monkeypatch.delenv("CI", raising=False)
    # The name of the machine in a store's notes, which is otherwise made
    # once and kept under the home folder: a `chartbook` a test runs in a
    # subprocess, with the real home, must not make one there. A test of
    # two machines clears it
    monkeypatch.setenv("CHARTBOOK_MACHINE_ID", "a-test-machine")
    # The user-level Claude Code skill, which commands compare with the
    # package: this machine's own copy, perhaps an old one, must not reach a
    # test's output (`chartbook check` warns of it)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(scratch / "claude"))
    # No git housekeeping in the background: `git commit` may start `gc
    # --auto` or maintenance detached, which goes on writing under
    # .git/objects after the command returns, and a test that then removes
    # the repository (shutil.rmtree) races it: "No such file or directory:
    # 'fb'" on CI, once in many runs. These are git's own environment
    # settings, read before any config file, so every git a test or a
    # command it runs starts has them
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "gc.auto")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "0")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "maintenance.auto")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "false")
    # Nor does the user's own ~/.chartbook (their catalog and settings) reach
    # a test; a test that moves HOME gets the one under it
    from pathlib import Path

    from chartbook import config

    from chartbook import backends

    real_home = Path.home()

    def config_dir() -> Path:
        return Path.home() / ".chartbook" if Path.home() != real_home else scratch / "user" / ".chartbook"

    monkeypatch.setattr(config, "get_global_config_dir", config_dir)
    monkeypatch.setattr(backends, "get_global_config_dir", config_dir)
    yield
    # The scratch store and caches go with their test. Found on CI on
    # 2026-10-21: the suite's temporary files, every test's stores and sites
    # kept until the end, filled the runner's disk at 99% of the run
    from tests.fixtures import remove_tree

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
