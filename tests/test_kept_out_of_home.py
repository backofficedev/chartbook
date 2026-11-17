"""Every test is kept out of this machine's ``~/.chartbook``, to its end: its store, its caches and its settings.

``tests/conftest.py`` points each of them at scratch folders before a test
starts. These are tests of that: what it sets stays set whatever a test does
with its own ``monkeypatch``.
"""

import os
import shutil
from pathlib import Path

from chartbook import config, rowhash

#: What conftest sets for every test, so that nothing asks this machine's home folder
KEPT = (
    "CHARTBOOK_STORE",
    "CHARTBOOK_GIT_CACHE",
    "CHARTBOOK_CACHE",
    "CHARTBOOK_SYSTEM_SETTINGS",
    "CHARTBOOK_TRUST",
    "CHARTBOOK_MACHINE_ID",
    "CLAUDE_CONFIG_DIR",
)


def _in_the_real_home(path) -> bool:
    return Path(path).resolve().is_relative_to((Path.home() / ".chartbook").resolve())


def _asked_now() -> dict:
    """Where ChartBook would read and write, asked now."""
    return {
        "the store": config.get_store_path(),
        "the cache": config.get_cache_path(),
        "the git cache": config.get_git_cache_path(),
        "the user's settings": config.get_global_settings_path(),
        "the organization's settings": config.get_system_settings_path(),
        "the trust file": config.get_trust_path(),
    }


def test_a_test_is_given_scratch_folders():
    assert all(os.environ.get(name) for name in KEPT), {name: os.environ.get(name) for name in KEPT}
    for what, path in _asked_now().items():
        assert not _in_the_real_home(path), (what, path)


def test_one_that_undoes_its_patches_is_kept_out_all_the_same(monkeypatch, tmp_path):
    """``monkeypatch.undo()`` half-way through a test takes away what the test set, and nothing of conftest's."""
    before = {name: os.environ.get(name) for name in KEPT}
    asked = _asked_now()
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another"))
    monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "another-cache"))
    monkeypatch.delenv("CHARTBOOK_MACHINE_ID")
    monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "another-home")
    assert config.get_store_path() == tmp_path / "another" and config.get_cache_path() == tmp_path / "another-cache"

    monkeypatch.undo()

    assert {name: os.environ.get(name) for name in KEPT} == before
    assert _asked_now() == asked
    for what, path in asked.items():
        assert not _in_the_real_home(path), (what, path)
    assert "CI" not in os.environ and "CHARTBOOK_BATCH" not in os.environ


def test_rows_hashed_after_an_undo_have_their_scratch_files_in_the_scratch_cache(monkeypatch):
    """How it was found: a table hashed after ``undo()`` made ``~/.chartbook/cache/rows`` on the machine the tests ran on."""
    monkeypatch.setattr(rowhash, "MOST_BYTES", 5_000)
    monkeypatch.undo()
    folder = rowhash._scratch_folder()
    try:
        assert folder.is_relative_to(config.get_cache_path() / "rows") and not _in_the_real_home(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
