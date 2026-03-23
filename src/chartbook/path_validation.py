"""Path validation utilities for detecting shell/platform mismatches.

Detects when users pass paths that don't match their shell environment
(e.g., Windows-style paths in Git Bash) and provides actionable suggestions.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from platform import system

import click

# Pattern for Windows drive letter paths like C:\ or D:\
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:\\")

# Pattern for UNC paths like \\server\share
_UNC_PATH_RE = re.compile(r"^\\\\")


@dataclass(frozen=True)
class ShellEnvironment:
    """Detected shell and platform environment."""

    os_name: str
    """Result of platform.system() — 'Windows', 'Linux', 'Darwin', etc."""

    is_mingw: bool = False
    """True if MSYSTEM env var is set (Git Bash, MSYS2, MINGW)."""

    is_cygwin: bool = False
    """True if running under Cygwin."""

    is_wsl: bool = False
    """True if running under Windows Subsystem for Linux."""

    msystem: str = ""
    """Value of MSYSTEM env var if set (e.g. 'MINGW64', 'UCRT64')."""

    @property
    def is_posix_on_windows(self) -> bool:
        """True if running a POSIX-like shell on a Windows system."""
        return self.is_mingw or self.is_cygwin or self.is_wsl

    @property
    def shell_style(self) -> str:
        """Return 'posix' or 'windows' based on the detected shell."""
        if self.is_posix_on_windows:
            return "posix"
        if self.os_name == "Windows":
            return "windows"
        return "posix"

    @property
    def shell_label(self) -> str:
        """Human-readable label for the detected shell environment."""
        if self.is_mingw:
            return f"Git Bash ({self.msystem})" if self.msystem else "Git Bash (MINGW)"
        if self.is_cygwin:
            return "Cygwin"
        if self.is_wsl:
            return "WSL"
        if self.os_name == "Windows":
            return "Windows"
        if self.os_name == "Darwin":
            return "macOS"
        if self.os_name == "Linux":
            return "Linux"
        return self.os_name or "Unknown"


def detect_shell_environment() -> ShellEnvironment:
    """Detect the current shell and platform environment.

    Uses environment variables and platform info to identify MINGW/Git Bash,
    Cygwin, WSL, and other environments.
    """
    os_name = system()
    msystem = os.environ.get("MSYSTEM", "")

    return ShellEnvironment(
        os_name=os_name,
        is_mingw=bool(msystem),
        is_cygwin=(sys.platform == "cygwin" or "CYGWIN" in os.environ),
        is_wsl=bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")),
        msystem=msystem,
    )


@dataclass
class PathDiagnostic:
    """A single diagnostic finding about a path."""

    level: str
    """'warning' or 'error'."""

    message: str
    """Human-readable description of the issue."""

    hint: str
    """Actionable suggestion for fixing the issue."""

    original_path: str
    """The path as originally provided."""

    suggested_path: str | None = None
    """Corrected path, if one can be computed."""


def suggest_posix_path(windows_path: str, env: ShellEnvironment) -> str | None:
    """Convert a Windows-style path to the appropriate POSIX equivalent.

    Returns None if the path doesn't look like a Windows path or the
    environment doesn't have a known conversion.
    """
    match = _WINDOWS_DRIVE_RE.match(windows_path)
    if not match:
        return None

    drive_letter = windows_path[0].lower()
    # Everything after "C:\" with backslashes replaced
    rest = windows_path[3:].replace("\\", "/")

    if env.is_wsl:
        return f"/mnt/{drive_letter}/{rest}"
    elif env.is_cygwin:
        return f"/cygdrive/{drive_letter}/{rest}"
    elif env.is_mingw:
        return f"/{drive_letter}/{rest}"

    return None


def _looks_like_windows_path(path: str) -> bool:
    """Check if a path looks like a Windows-style path."""
    return bool(_WINDOWS_DRIVE_RE.match(path))


def _has_backslashes(path: str) -> bool:
    """Check if a path contains backslashes (potential Windows separator)."""
    return "\\" in path


def diagnose_path(raw_path: str, env: ShellEnvironment) -> list[PathDiagnostic]:
    """Analyze a path string for potential platform/shell mismatches.

    This is the core reusable check — works for both CLI arguments
    and paths read from TOML files.

    :param raw_path: The path string to analyze.
    :param env: The detected shell environment.
    :returns: List of diagnostics (may be empty if path looks fine).
    """
    diagnostics: list[PathDiagnostic] = []

    # Check 1: Windows drive letter path in a POSIX-like shell
    if _looks_like_windows_path(raw_path) and env.is_posix_on_windows:
        suggested = suggest_posix_path(raw_path, env)
        hint_parts = [
            f"In {env.shell_label}, use POSIX-style paths instead of Windows paths.",
        ]
        if suggested:
            hint_parts.append(f"Try: {suggested}")
        diagnostics.append(
            PathDiagnostic(
                level="warning",
                message=(
                    f"Path looks like a Windows path, but you're running in "
                    f"{env.shell_label}."
                ),
                hint="\n".join(hint_parts),
                original_path=raw_path,
                suggested_path=suggested,
            )
        )
        return diagnostics  # No need for further checks

    # Check 2: Backslashes in a non-Windows runtime
    if _has_backslashes(raw_path) and env.os_name != "Windows":
        diagnostics.append(
            PathDiagnostic(
                level="warning",
                message="Path contains backslashes, which are not path separators on this platform.",
                hint="Use forward slashes (/) instead of backslashes (\\).",
                original_path=raw_path,
                suggested_path=raw_path.replace("\\", "/"),
            )
        )
        return diagnostics

    # Check 3: Backslashes in MINGW with native Windows Python
    # (Python can resolve them, but it's fragile and confusing)
    if _has_backslashes(raw_path) and env.is_mingw and env.os_name == "Windows":
        suggested = suggest_posix_path(raw_path, env) if _looks_like_windows_path(raw_path) else raw_path.replace("\\", "/")
        diagnostics.append(
            PathDiagnostic(
                level="warning",
                message=(
                    "Path contains backslashes. While this may work with Windows Python, "
                    f"it can cause issues in {env.shell_label}."
                ),
                hint=f"Use forward slashes for consistency. Try: {suggested}",
                original_path=raw_path,
                suggested_path=suggested,
            )
        )

    # Check 4: UNC paths in POSIX-like shell
    if _UNC_PATH_RE.match(raw_path) and env.is_posix_on_windows:
        diagnostics.append(
            PathDiagnostic(
                level="warning",
                message=f"UNC path detected in {env.shell_label}.",
                hint="UNC paths may not resolve correctly. Consider mapping to a drive letter or using the POSIX mount point.",
                original_path=raw_path,
            )
        )

    return diagnostics


def validate_cli_paths(
    paths: tuple[str, ...] | list[str],
    env: ShellEnvironment,
    auto_confirm: bool = False,
) -> list[str]:
    """Validate CLI path arguments and warn about potential issues.

    Runs :func:`diagnose_path` on each path, prints warnings, and
    optionally prompts the user to continue or use a suggested path.

    :param paths: Raw path strings from CLI arguments.
    :param env: The detected shell environment.
    :param auto_confirm: If True, skip confirmation prompts (like -y flag).
    :returns: List of path strings to use (may include corrected paths).
    """
    result_paths: list[str] = []
    all_diagnostics: list[PathDiagnostic] = []

    for raw_path in paths:
        diags = diagnose_path(raw_path, env)
        if not diags:
            result_paths.append(raw_path)
            continue

        all_diagnostics.extend(diags)
        for d in diags:
            _print_diagnostic(d)

        # If we have a suggestion, offer it
        best_suggestion = next(
            (d.suggested_path for d in diags if d.suggested_path), None
        )

        if best_suggestion and not auto_confirm:
            if click.confirm(f"  Use suggested path instead?", default=True):
                result_paths.append(best_suggestion)
                continue

        if not auto_confirm:
            if not click.confirm("  Continue with the original path?", default=False):
                raise SystemExit(1)

        result_paths.append(raw_path)

    return result_paths


def check_toml_path(
    raw_path: str,
    env: ShellEnvironment,
    field_name: str,
    file_path: str,
) -> list[PathDiagnostic]:
    """Check a path value read from a TOML file for potential issues.

    Wraps :func:`diagnose_path` with TOML context for better messages.

    :param raw_path: The path string from the TOML file.
    :param env: The detected shell environment.
    :param field_name: The TOML field name (e.g. 'path_to_pipeline').
    :param file_path: The TOML file path for context in messages.
    :returns: List of diagnostics with TOML context.
    """
    base_diags = diagnose_path(raw_path, env)
    if not base_diags:
        return []

    contextualized: list[PathDiagnostic] = []
    for d in base_diags:
        contextualized.append(
            PathDiagnostic(
                level=d.level,
                message=f"In {file_path}, field '{field_name}': {d.message}",
                hint=d.hint,
                original_path=d.original_path,
                suggested_path=d.suggested_path,
            )
        )
    return contextualized


def _print_diagnostic(diag: PathDiagnostic) -> None:
    """Print a path diagnostic to stderr with colored formatting."""
    if diag.level == "error":
        prefix = click.style("Error: ", fg="red", bold=True)
    else:
        prefix = click.style("Warning: ", fg="yellow", bold=True)

    click.echo(f"{prefix}{diag.message}", err=True)
    click.echo(f"  Path: {click.style(diag.original_path, fg='cyan')}", err=True)
    if diag.suggested_path:
        click.echo(
            f"  Suggested: {click.style(diag.suggested_path, fg='green')}", err=True
        )
    click.echo(f"  {diag.hint}", err=True)
    click.echo("", err=True)
