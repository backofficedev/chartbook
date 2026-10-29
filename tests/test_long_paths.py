"""Windows refuses a path of 260 characters or more unless long paths are on (#136): the store says so before it writes.

Run on every system, as Windows with long paths off.
"""

import subprocess

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.store import FolderStore, PathTooLongError


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)


def _git(directory, *arguments):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=directory, check=True, capture_output=True)


@pytest.fixture
def pipeline(tmp_path):
    folder = tmp_path.resolve() / "rates"
    (folder / "_data").mkdir(parents=True)
    (folder / "_data" / "treasury.parquet").write_bytes(b"rates-1")
    (folder / "chartbook.toml").write_text(tomli_w.dumps({
        "project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
    }), encoding="utf-8")
    (folder / ".gitignore").write_text("_data/\n", encoding="utf-8")
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-qm", "one")
    return folder


def test_too_long_says_the_length_the_limit_and_both_ways_out(windows):
    said = store_module.too_long("C:\\" + "x" * 300)
    assert "303 characters long" in said and "260 or more" in said
    assert "LongPathsEnabled" in said and "a shorter folder" in said and "CHARTBOOK_STORE" in said
    assert store_module.too_long("C:\\short") is None


def test_nothing_is_said_where_long_paths_are_taken(monkeypatch):
    monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
    monkeypatch.setattr(store_module, "long_paths_enabled", lambda: True)
    assert store_module.too_long("C:\\" + "x" * 300) is None


def test_a_snapshot_that_would_write_too_long_a_path_writes_nothing_and_says_why(windows, pipeline, tmp_path, monkeypatch):
    root = tmp_path.resolve() / ("deep" * 50) / "store"  # a store in a deep folder, as #136's
    monkeypatch.setenv("CHARTBOOK_STORE", str(root))
    with pytest.raises(PathTooLongError, match="characters long, and Windows refuses a path of 260 or more"):
        snapshot.make(pipeline)
    assert not any(path.is_file() for path in (root / "pipelines").rglob("*")) if (root / "pipelines").exists() else True


def test_store_info_warns_when_the_folder_leaves_too_little_room(windows, tmp_path, monkeypatch):
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path.resolve() / ("deep" * 40) / "store"))
    said = CliRunner().invoke(main, ["store", "info"])
    assert said.exit_code == 0 and "Warning: the store's folder is" in said.output and "LongPathsEnabled" in said.output


def test_a_short_folder_is_not_warned_about(windows, monkeypatch):
    import os

    monkeypatch.setenv("CHARTBOOK_STORE", os.path.abspath(os.sep + "s"))  # never made: info writes nothing
    said = CliRunner().invoke(main, ["store", "info"])
    assert said.exit_code == 0 and "Warning" not in said.output


def test_the_command_says_it_and_no_traceback(windows, pipeline, tmp_path, monkeypatch):
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path.resolve() / ("deep" * 50) / "store"))
    said = CliRunner().invoke(main, ["snapshot", "--project-dir", str(pipeline)])
    assert said.exit_code == 1 and "Traceback" not in said.output
    assert "Windows refuses a path of 260 or more" in said.output
