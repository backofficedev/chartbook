"""Tests for the path_validation module."""

import pytest
from unittest.mock import patch

from chartbook.path_validation import (
    ShellEnvironment,
    detect_shell_environment,
    diagnose_path,
    suggest_posix_path,
    validate_cli_paths,
    check_toml_path,
)


# ── Fixtures for common environments ──────────────────────────────


@pytest.fixture
def mingw_env():
    return ShellEnvironment(
        os_name="Windows", is_mingw=True, msystem="MINGW64",
    )


@pytest.fixture
def wsl_env():
    return ShellEnvironment(os_name="Linux", is_wsl=True)


@pytest.fixture
def cygwin_env():
    return ShellEnvironment(os_name="Windows", is_cygwin=True)


@pytest.fixture
def plain_windows_env():
    return ShellEnvironment(os_name="Windows")


@pytest.fixture
def macos_env():
    return ShellEnvironment(os_name="Darwin")


@pytest.fixture
def linux_env():
    return ShellEnvironment(os_name="Linux")


# ── detect_shell_environment ──────────────────────────────────────


class TestDetectShellEnvironment:

    def test_plain_macos(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Darwin")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "darwin"})())

        env = detect_shell_environment()
        assert env.os_name == "Darwin"
        assert not env.is_mingw
        assert not env.is_cygwin
        assert not env.is_wsl
        assert env.shell_style == "posix"
        assert env.shell_label == "macOS"

    def test_plain_linux(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Linux")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "linux"})())

        env = detect_shell_environment()
        assert env.os_name == "Linux"
        assert not env.is_wsl
        assert env.shell_style == "posix"

    def test_plain_windows(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Windows")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "win32"})())

        env = detect_shell_environment()
        assert env.os_name == "Windows"
        assert not env.is_mingw
        assert env.shell_style == "windows"
        assert env.shell_label == "Windows"

    def test_mingw64(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Windows")
        monkeypatch.setenv("MSYSTEM", "MINGW64")
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "win32"})())

        env = detect_shell_environment()
        assert env.is_mingw
        assert env.msystem == "MINGW64"
        assert env.is_posix_on_windows
        assert env.shell_style == "posix"
        assert "MINGW64" in env.shell_label

    def test_wsl(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Linux")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "linux"})())

        env = detect_shell_environment()
        assert env.is_wsl
        assert env.is_posix_on_windows
        assert env.shell_label == "WSL"

    def test_cygwin(self, monkeypatch):
        monkeypatch.setattr("chartbook.path_validation.system", lambda: "Windows")
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        monkeypatch.delenv("CYGWIN", raising=False)
        monkeypatch.setattr("chartbook.path_validation.sys", type("sys", (), {"platform": "cygwin"})())

        env = detect_shell_environment()
        assert env.is_cygwin
        assert env.is_posix_on_windows


# ── suggest_posix_path ────────────────────────────────────────────


class TestSuggestPosixPath:

    def test_mingw_conversion(self, mingw_env):
        assert suggest_posix_path(r"C:\Users\student\proj", mingw_env) == "/c/Users/student/proj"

    def test_mingw_d_drive(self, mingw_env):
        assert suggest_posix_path(r"D:\data\files", mingw_env) == "/d/data/files"

    def test_wsl_conversion(self, wsl_env):
        assert suggest_posix_path(r"C:\Users\student\proj", wsl_env) == "/mnt/c/Users/student/proj"

    def test_cygwin_conversion(self, cygwin_env):
        assert suggest_posix_path(r"C:\Users\student\proj", cygwin_env) == "/cygdrive/c/Users/student/proj"

    def test_plain_windows_returns_none(self, plain_windows_env):
        assert suggest_posix_path(r"C:\Users\student", plain_windows_env) is None

    def test_non_windows_path_returns_none(self, mingw_env):
        assert suggest_posix_path("/home/user/proj", mingw_env) is None

    def test_lowercase_drive_letter(self, mingw_env):
        assert suggest_posix_path(r"c:\users\foo", mingw_env) == "/c/users/foo"


# ── diagnose_path ─────────────────────────────────────────────────


class TestDiagnosePath:

    def test_normal_posix_path_no_diagnostics(self, macos_env):
        assert diagnose_path("/Users/student/proj", macos_env) == []

    def test_normal_posix_path_on_linux(self, linux_env):
        assert diagnose_path("/home/student/proj", linux_env) == []

    def test_relative_path_no_diagnostics(self, macos_env):
        assert diagnose_path("../some/path", macos_env) == []

    def test_normal_windows_path_on_windows(self, plain_windows_env):
        assert diagnose_path(r"C:\Users\student", plain_windows_env) == []

    def test_windows_path_in_mingw(self, mingw_env):
        diags = diagnose_path(r"C:\Users\student\proj", mingw_env)
        assert len(diags) == 1
        assert diags[0].level == "warning"
        assert "Windows path" in diags[0].message
        assert "Git Bash" in diags[0].message
        assert diags[0].suggested_path == "/c/Users/student/proj"

    def test_windows_path_in_wsl(self, wsl_env):
        diags = diagnose_path(r"C:\Users\student\proj", wsl_env)
        assert len(diags) == 1
        assert diags[0].suggested_path == "/mnt/c/Users/student/proj"

    def test_windows_path_in_cygwin(self, cygwin_env):
        diags = diagnose_path(r"C:\Users\student\proj", cygwin_env)
        assert len(diags) == 1
        assert diags[0].suggested_path == "/cygdrive/c/Users/student/proj"

    def test_backslashes_on_macos(self, macos_env):
        diags = diagnose_path(r"some\path\here", macos_env)
        assert len(diags) == 1
        assert "backslashes" in diags[0].message
        assert diags[0].suggested_path == "some/path/here"

    def test_backslashes_on_linux(self, linux_env):
        diags = diagnose_path(r"some\path\here", linux_env)
        assert len(diags) == 1
        assert "backslashes" in diags[0].message

    def test_backslashes_in_mingw_native_python(self):
        env = ShellEnvironment(os_name="Windows", is_mingw=True, msystem="MINGW64")
        diags = diagnose_path(r"some\path\here", env)
        assert len(diags) == 1
        assert "backslashes" in diags[0].message
        assert diags[0].suggested_path == "some/path/here"

    def test_unc_path_in_mingw(self, mingw_env):
        diags = diagnose_path(r"\\server\share\folder", mingw_env)
        assert any("UNC" in d.message for d in diags)

    def test_glob_pattern_not_flagged(self, macos_env):
        assert diagnose_path("/Users/student/pipelines/*", macos_env) == []


# ── validate_cli_paths ────────────────────────────────────────────


class TestValidateCliPaths:

    def test_clean_paths_pass_through(self, macos_env):
        paths = ("/Users/a", "/Users/b")
        result = validate_cli_paths(paths, macos_env)
        assert result == ["/Users/a", "/Users/b"]

    def test_auto_confirm_keeps_original(self, mingw_env):
        paths = (r"C:\Users\student",)
        result = validate_cli_paths(paths, mingw_env, auto_confirm=True)
        assert result == [r"C:\Users\student"]

    def test_user_accepts_suggestion(self, mingw_env, monkeypatch):
        monkeypatch.setattr("click.confirm", lambda msg, **kw: True)
        paths = (r"C:\Users\student",)
        result = validate_cli_paths(paths, mingw_env)
        assert result == ["/c/Users/student"]

    def test_user_rejects_suggestion_and_continues(self, mingw_env, monkeypatch):
        # First confirm (use suggestion?) -> No, second confirm (continue?) -> Yes
        responses = iter([False, True])
        monkeypatch.setattr("click.confirm", lambda msg, **kw: next(responses))
        paths = (r"C:\Users\student",)
        result = validate_cli_paths(paths, mingw_env)
        assert result == [r"C:\Users\student"]

    def test_user_rejects_all_exits(self, mingw_env, monkeypatch):
        # First confirm (use suggestion?) -> No, second confirm (continue?) -> No
        responses = iter([False, False])
        monkeypatch.setattr("click.confirm", lambda msg, **kw: next(responses))
        paths = (r"C:\Users\student",)
        with pytest.raises(SystemExit):
            validate_cli_paths(paths, mingw_env)

    def test_mixed_paths(self, mingw_env, monkeypatch):
        monkeypatch.setattr("click.confirm", lambda msg, **kw: True)
        paths = ("/c/good/path", r"C:\bad\path")
        result = validate_cli_paths(paths, mingw_env)
        assert result == ["/c/good/path", "/c/bad/path"]


# ── check_toml_path ──────────────────────────────────────────────


class TestCheckTomlPath:

    def test_clean_path_no_diagnostics(self, macos_env):
        result = check_toml_path("../data/file.parquet", macos_env, "path_to_parquet_data", "chartbook.toml")
        assert result == []

    def test_windows_path_includes_context(self, mingw_env):
        result = check_toml_path(
            r"C:\data\file.parquet",
            mingw_env,
            "path_to_parquet_data",
            "chartbook.toml",
        )
        assert len(result) == 1
        assert "chartbook.toml" in result[0].message
        assert "path_to_parquet_data" in result[0].message
        assert result[0].suggested_path == "/c/data/file.parquet"

    def test_backslashes_include_field_context(self, linux_env):
        result = check_toml_path(
            r"data\file.parquet",
            linux_env,
            "path_to_parquet_data",
            "/home/user/chartbook.toml",
        )
        assert len(result) == 1
        assert "path_to_parquet_data" in result[0].message
