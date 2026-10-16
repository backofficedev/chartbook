"""The settings in layers: the environment, the user's file, the organization's file, the default."""

from pathlib import Path

import pytest
import tomli_w

from chartbook import config


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A user settings file and an organization's, both empty, both named by the test."""
    user = tmp_path / "home" / ".chartbook"
    user.mkdir(parents=True)
    system = tmp_path / "etc" / "settings.toml"
    system.parent.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: user)
    monkeypatch.setenv(config.SYSTEM_SETTINGS_ENV_VAR, str(system))
    monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
    monkeypatch.delenv(config.GIT_CACHE_ENV_VAR, raising=False)
    return user / "settings.toml", system


def _write(path: Path, settings: dict) -> None:
    path.write_text(tomli_w.dumps(settings))


class TestTheLayers:
    def test_nothing_set_means_the_folder_under_home(self, files):
        user, _ = files
        assert config.get_store_path() == (user.parent / "store").resolve()

    def test_the_organization_sets_the_store_and_the_user_keeps_their_own_catalog(self, files, tmp_path):
        user, system = files
        _write(system, {"store": {"url": str(tmp_path / "shared-store")}, "catalog": {"path": "/org/catalog.toml"}})
        _write(user, {"catalog": {"path": "/me/catalog.toml"}})
        assert config.get_store_path() == (tmp_path / "shared-store").resolve()
        assert config.get_default_catalog_path() == Path("/me/catalog.toml")

    def test_the_user_overrides_the_organization_key_by_key(self, files, tmp_path):
        user, system = files
        _write(system, {"store": {"url": str(tmp_path / "shared-store")}, "git": {"path": str(tmp_path / "shared-git")}})
        _write(user, {"store": {"url": str(tmp_path / "my-store")}})
        assert config.get_store_path() == (tmp_path / "my-store").resolve()
        assert config.get_git_cache_path() == (tmp_path / "shared-git").resolve()

    def test_the_environment_sits_above_both(self, files, tmp_path, monkeypatch):
        user, system = files
        _write(system, {"store": {"url": str(tmp_path / "shared-store")}})
        _write(user, {"store": {"url": str(tmp_path / "my-store")}})
        monkeypatch.setenv(config.STORE_ENV_VAR, str(tmp_path / "ci-store"))
        assert config.get_store_path() == (tmp_path / "ci-store").resolve()

    def test_the_system_file_has_a_platform_default_when_nothing_names_it(self, monkeypatch):
        monkeypatch.delenv(config.SYSTEM_SETTINGS_ENV_VAR, raising=False)
        path = config.get_system_settings_path()
        assert path.name == "settings.toml" and "chartbook" in path.parts


class TestTheStoreIsAUrl:
    def test_a_bare_path_and_a_file_url_are_a_folder(self, files, tmp_path):
        user, _ = files
        _write(user, {"store": {"url": "file://" + str(tmp_path / "a-store")}})
        assert config.store_kind(config.get_store_url()) == "folder"
        assert config.get_store_path() == (tmp_path / "a-store").resolve()
        assert config.store_kind("~/stores/one") == "folder"
        assert config.store_kind("C:\\stores\\one") == "folder"  # a drive letter is not a scheme

    def test_another_kind_of_store_is_named_and_refused_until_it_is_built(self, files):
        user, _ = files
        _write(user, {"store": {"url": "s3://bucket/chartbook"}})
        assert config.store_kind(config.get_store_url()) == "s3"
        with pytest.raises(ValueError, match="is a s3:// store, and this needs a folder"):
            config.get_store_path()

    def test_the_old_path_key_is_read_once_with_a_warning(self, files, tmp_path):
        user, _ = files
        _write(user, {"store": {"path": str(tmp_path / "old-store")}})
        with pytest.warns(UserWarning, match=r"\[store\] path is now \[store\] url"):
            assert config.get_store_path() == (tmp_path / "old-store").resolve()

    def test_a_malformed_store_table_names_the_file_it_is_in(self, files):
        user, system = files
        _write(system, {"store": {"url": ""}})
        # The organization's fault is said, and its file ignored
        with pytest.warns(UserWarning, match=r"etc/settings.toml: \[store\] needs a 'url'.*It is ignored"):
            assert config.get_store_path() == (user.parent / "store").resolve()
        _write(user, {"store": "nope"})
        # The user's fault is theirs to fix
        with pytest.raises(ValueError, match=r"\.chartbook/settings.toml: \[store\] must be a table"):
            config.get_store_path()


class TestWhatTheReviewFound:
    def test_a_users_old_path_key_still_wins_over_the_organizations_url(self, files, tmp_path):
        """Found by a reviewer: the layers were merged before the old key was read, so the
        organization's `url` shadowed the user's `path` without a word."""
        user, system = files
        _write(system, {"store": {"url": str(tmp_path / "shared-store")}})
        _write(user, {"store": {"path": str(tmp_path / "my-old-store")}})
        with pytest.warns(UserWarning, match=r"\.chartbook/settings\.toml: \[store\] path is now \[store\] url"):
            assert config.get_store_path() == (tmp_path / "my-old-store").resolve()

    def test_a_faulty_organization_file_is_a_warning_and_ignored(self, files, tmp_path):
        user, system = files
        system.write_text("this = [not toml")
        with pytest.warns(UserWarning, match="is not valid TOML.*It is ignored"):
            assert config.get_store_path() == (user.parent / "store").resolve()
        system.write_text("")
        system.chmod(0o000)
        try:
            with pytest.warns(UserWarning, match="cannot be read.*It is ignored"):
                config.get_store_path()
        finally:
            system.chmod(0o644)

    def test_a_named_organization_file_that_is_not_there_is_said(self, files, tmp_path, monkeypatch):
        monkeypatch.setenv(config.SYSTEM_SETTINGS_ENV_VAR, str(tmp_path / "nowhere.toml"))
        with pytest.warns(UserWarning, match="nowhere.toml, named as the organization's settings, is not a file"):
            config.read_settings()

    def test_a_faulty_user_file_names_itself(self, files):
        user, _ = files
        user.write_text("this = [not toml")
        with pytest.raises(ValueError, match=r"\.chartbook/settings\.toml, the user's settings, is not valid TOML"):
            config.get_store_path()
        user.write_text("catalog = 5\n")
        with pytest.raises(ValueError, match=r"\[catalog\] must be a table"):
            config.get_default_catalog_path()

    def test_a_relative_folder_is_relative_to_its_settings_file(self, files, tmp_path, monkeypatch):
        user, system = files
        _write(system, {"store": {"url": "relative/store"}, "git": {"path": "relative/git"}})
        monkeypatch.chdir(tmp_path / "home")
        assert config.get_store_path() == (system.parent / "relative" / "store").resolve()
        assert config.get_git_cache_path() == (system.parent / "relative" / "git").resolve()

    def test_file_urls_in_any_case_and_with_a_host(self, files, tmp_path):
        user, _ = files
        _write(user, {"store": {"url": "FILE://" + str(tmp_path / "upper")}})
        assert config.get_store_path() == (tmp_path / "upper").resolve()
        _write(user, {"store": {"url": "file://server/share"}})
        with pytest.raises(ValueError, match="names a host"):
            config.get_store_path()

    def test_the_cli_says_a_settings_fault_in_one_line(self, files, tmp_path, monkeypatch):
        """Found by a reviewer: `chartbook ls` and `chartbook config` ended in a traceback on a
        faulty user file, and a warning printed as Python's file, line and source line."""
        from click.testing import CliRunner

        from chartbook.cli import main

        user, _ = files
        user.write_text("x = [\n")
        listed = CliRunner().invoke(main, ["ls"])
        assert listed.exit_code == 1
        assert "Error:" in listed.output and "is not valid TOML" in listed.output and "Traceback" not in listed.output
        _write(user, {"store": {"path": str(tmp_path / "old-store")}})
        import warnings

        with warnings.catch_warnings():
            # Python shows a warning once per place in one process; a command
            # is a process of its own, and this test process has warned here before
            warnings.simplefilter("always")
            verified = CliRunner().invoke(main, ["store", "verify"])
        assert "Warning: " in verified.output and "[store] path is now [store] url" in verified.output
        assert "UserWarning" not in verified.output and "config.py" not in verified.output

    def test_a_home_of_an_unknown_user_is_a_fault_of_the_file(self, files):
        """Found by a reviewer: `~nosuchuser/store` raised a RuntimeError that nothing caught."""
        user, system = files
        _write(system, {"store": {"url": "~nosuchuser_chartbook/store"}})
        with pytest.warns(UserWarning, match="names a user this machine does not know.*It is ignored"):
            assert config.get_store_path() == (user.parent / "store").resolve()
        _write(user, {"store": {"url": "~nosuchuser_chartbook/store"}})
        with pytest.raises(ValueError, match=r"\.chartbook/settings\.toml: .*names a user this machine does not know"):
            config.get_store_path()
