"""Every test is kept out of this machine's own store, caches and settings, to its end, and so is every fixture.

``tests/conftest.py`` points each of them at scratch folders, around the
whole run and around every test (:func:`tests.fixtures.kept_out_of_home`).
These are tests of that: all that ChartBook would read or write is under
this run's temporary folder, whatever a test does with its own
``monkeypatch``, and before a test's own scratch folders are there.
"""

import os
import shutil
from pathlib import Path

import pytest

from chartbook import backends, config, rowhash
from tests.fixtures import kept_out_of_home

#: Set to a folder or a file under the scratch folders
FOLDERS = ("CHARTBOOK_STORE", "CHARTBOOK_GIT_CACHE", "CHARTBOOK_CACHE", "CHARTBOOK_SYSTEM_SETTINGS", "CLAUDE_CONFIG_DIR")
#: Set, to what a test needs
SET = {"CHARTBOOK_TRUST": "all", "CHARTBOOK_MACHINE_ID": "a-test-machine", "GIT_CONFIG_COUNT": "2"}
#: Taken away, whatever the shell or CI set
GONE = ("CI", "CHARTBOOK_BATCH")


def _asked_now() -> dict:
    """Every place ChartBook would read or write for this user, asked now."""
    return {
        **{name: os.environ.get(name) for name in (*FOLDERS, *SET, *GONE)},
        "the store": config.get_store_path(),
        "the cache": config.get_cache_path(),
        "the git cache": config.get_git_cache_path(),
        "the user's folder": config.get_global_config_dir(),
        "the user's folder, for the sources": backends.get_global_config_dir(),
        "the user's settings": config.get_global_settings_path(),
        "the organization's settings": config.get_system_settings_path(),
        "the trust file": config.get_trust_path(),
    }


def _all_scratch(asked: dict, under: Path) -> None:
    """Under this run's temporary folder: not the home folder, and not a store that the settings or the shell name."""
    under = under.resolve()
    for what, value in asked.items():
        if what in SET:
            assert value == SET[what], (what, value)
        elif what in GONE:
            assert value is None, (what, value)
        else:
            assert value and Path(value).resolve().is_relative_to(under), (what, value)


def test_a_test_is_given_scratch_folders(tmp_path_factory):
    _all_scratch(_asked_now(), tmp_path_factory.getbasetemp())


def test_one_that_undoes_its_patches_is_kept_out_all_the_same(monkeypatch, tmp_path, tmp_path_factory):
    """``monkeypatch.undo()`` half-way through a test takes away what the test set, and nothing of conftest's."""
    asked = _asked_now()
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another"))
    monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "another-cache"))
    monkeypatch.delenv("CHARTBOOK_MACHINE_ID")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "another-home")
    monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path / "another-home")
    assert config.get_store_path() == tmp_path / "another" and config.get_cache_path() == tmp_path / "another-cache"

    monkeypatch.undo()

    assert _asked_now() == asked
    _all_scratch(asked, tmp_path_factory.getbasetemp())


def test_rows_hashed_after_an_undo_have_their_scratch_files_in_the_scratch_cache(monkeypatch, tmp_path_factory):
    """How it was found: a table hashed after ``undo()`` made ``~/.chartbook/cache/rows`` on the machine the tests ran on."""
    monkeypatch.setattr(rowhash, "MOST_BYTES", 5_000)
    monkeypatch.undo()
    # Asked before a folder is made, so that a guard that is gone makes none where it should not
    assert config.get_cache_path().resolve().is_relative_to(tmp_path_factory.getbasetemp().resolve())
    folder = rowhash._scratch_folder()
    try:
        assert folder.is_relative_to(config.get_cache_path() / "rows")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class TestAFixtureOfAClass:
    """Set up before the test's own scratch folders are: it has the run's."""

    @pytest.fixture(scope="class")
    def asked_while_set_up(self):
        return _asked_now()

    def test_it_is_kept_out_too(self, asked_while_set_up, tmp_path_factory):
        _all_scratch(asked_while_set_up, tmp_path_factory.getbasetemp())

    def test_and_the_test_has_folders_of_its_own(self, asked_while_set_up):
        mine = _asked_now()
        assert all(mine[name] != asked_while_set_up[name] for name in FOLDERS)


class TestWhatKeepsThemOut:
    """:func:`tests.fixtures.kept_out_of_home` itself: what it sets, and that it is all undone."""

    def test_it_sets_every_place_and_puts_them_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CI", "true")  # as on a runner
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")  # as under `chartbook run`
        before = _asked_now()
        with kept_out_of_home(tmp_path / "scratch"):
            within = _asked_now()
            _all_scratch(within, tmp_path / "scratch")
            assert within["the store"] == tmp_path / "scratch" / "store" and within["the cache"] == tmp_path / "scratch" / "cache"
            assert os.environ["GIT_CONFIG_KEY_0"] == "gc.auto" and os.environ["GIT_CONFIG_VALUE_0"] == "0"
            assert os.environ["GIT_CONFIG_KEY_1"] == "maintenance.auto" and os.environ["GIT_CONFIG_VALUE_1"] == "false"
        assert _asked_now() == before and before["CI"] == "true" and before["CHARTBOOK_BATCH"] == "1"

    def test_a_home_folder_that_was_moved_is_the_one_asked(self, tmp_path, monkeypatch):
        """A test that moves HOME is given the ``.chartbook`` under it: its own, never this machine's."""
        with kept_out_of_home(tmp_path / "scratch"):
            monkeypatch.setenv("HOME", str(tmp_path / "moved"))
            monkeypatch.setenv("USERPROFILE", str(tmp_path / "moved"))  # Windows reads home from here
            assert config.get_global_config_dir() == tmp_path / "moved" / ".chartbook"
            assert backends.get_global_config_dir() == tmp_path / "moved" / ".chartbook"

    def test_one_that_fails_half_way_leaves_nothing_set(self, tmp_path, monkeypatch):
        """What it had set by then is undone: nothing of it reaches the tests after."""
        before = _asked_now()

        def no_home():
            raise RuntimeError("no home folder")

        monkeypatch.setattr(Path, "home", no_home)
        with pytest.raises(RuntimeError, match="no home folder"):
            with kept_out_of_home(tmp_path / "scratch"):
                pytest.fail("entered")
        monkeypatch.undo()
        assert _asked_now() == before

    def test_an_error_inside_it_undoes_it_too(self, tmp_path):
        before = _asked_now()
        with pytest.raises(KeyError):
            with kept_out_of_home(tmp_path / "scratch"):
                raise KeyError("in the test")
        assert _asked_now() == before
