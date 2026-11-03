"""A command's output read through a pipe, as an agent always reads it (#164)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# A command that prints what lineage, store ls and pin print, run through the CLI's own entry
SCRIPT = """
import click
from chartbook import cli

@cli.main.command("print-tree")
def print_tree():
    click.echo("my_pipeline (this folder)")
    click.echo("\\u251c\\u2500\\u2500 acme/rates \\u2192 3f2a1c9 \\u00b7 \\u2026")

cli.main(["print-tree"])
"""


def test_a_piped_command_prints_what_the_code_page_has_not():
    """Windows writes a pipe in the ANSI code page (cp1252), which has no tree characters: as PYTHONIOENCODING=cp1252 makes it here."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONPATH": str(ROOT / "src")}
    ran = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, env=env, timeout=120)
    assert ran.returncode == 0, ran.stderr.decode("utf-8", "replace")
    assert ran.stdout.decode("utf-8").splitlines()[-1] == "├── acme/rates → 3f2a1c9 · …"


@pytest.mark.skipif(sys.platform != "win32", reason="the code page a pipe is written in is Windows' own")
def test_a_piped_command_on_windows_as_it_is():
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONPATH"] = str(ROOT / "src")
    ran = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, env=env, timeout=120)
    assert ran.returncode == 0, ran.stderr.decode("utf-8", "replace")
    assert "→" in ran.stdout.decode("utf-8")


def test_a_console_and_a_utf8_stream_are_left_as_they_are():
    import io

    from chartbook.cli import _utf8_output

    class Console(io.TextIOWrapper):
        def isatty(self):
            return True

    console = Console(io.BytesIO(), encoding="cp1252")
    piped = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    already = io.TextIOWrapper(io.BytesIO(), encoding="UTF-8")
    _utf8_output([console, piped, already, None])
    assert (console.encoding, piped.encoding, already.encoding) == ("cp1252", "utf-8", "UTF-8")
