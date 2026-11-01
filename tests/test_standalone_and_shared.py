"""Snapshots are standalone or shared, and the store says so: a README in each pipeline's folder, `store ls`, and a gc reminder.

``docs_src/design/plan-data-reads.md``, step 4.
"""

import re
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, snapshot
from chartbook.cli import main
from chartbook.store import README_FILE, FolderStore
from tests.fixtures import commit_pipeline


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return FolderStore(work / "store")


def _write_year(folder: Path, year: int, values: list) -> None:
    part = folder / "_data" / "articles" / f"year={year}"
    part.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"n": values}).write_parquet(part / "part-0.parquet")


@pytest.fixture
def news(work, store):
    folder = work / "news"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "news"}, "dataframes": {"articles": {"path": "./_data/articles", "docs": "d"}}}),
        encoding="utf-8", newline="\n",
    )
    _write_year(folder, 2023, [1, 2])
    commit_pipeline(folder)
    return folder


class TestTheReadme:
    def test_the_first_snapshot_leaves_one_and_later_ones_leave_it_alone(self, news, store):
        first = snapshot.make(news, store=store).snapshot
        note = Path(first.path).parent.parent.parent / README_FILE
        assert note.is_file() and note.parent == store.root / "pipelines" / "news"
        text = note.read_text(encoding="utf-8")
        assert "chartbook store gc" in text and "shared" in text and "standalone" in text and "Do not delete" in text
        note.write_text(text + "A note of my own.\n", encoding="utf-8", newline="\n")
        _write_year(news, 2024, [3])
        snapshot.make(news, store=store)
        assert note.read_text(encoding="utf-8").endswith("A note of my own.\n")  # nothing in the store is rewritten

    def test_gc_leaves_it(self, news, store):
        from chartbook import lock

        snapshot.make(news, store=store, made_at="2026-01-01T00:00:00.000000Z")
        _write_year(news, 2024, [3])
        snapshot.make(news, store=store)
        plan = lock.plan_gc(store, keep_days=0)
        assert plan.snapshots_delete
        lock.run_gc(plan, store)
        assert (store.root / "pipelines" / "news" / README_FILE).is_file()


class TestStoreLs:
    def test_standalone_then_shared(self, news, store):
        first = snapshot.make(news, store=store).snapshot
        _write_year(news, 2024, [3])
        second = snapshot.make(news, store=store).snapshot
        result = CliRunner().invoke(main, ["store", "ls"])
        assert result.exit_code == 0, result.output
        lines = [line for line in result.output.splitlines() if line.startswith("  20")]
        assert len(lines) == 2
        assert Path(first.path).parent.parent.name in lines[0] and "standalone" in lines[0] and "earlier folders" not in lines[0]
        # The first year's part and the unchanged documents are kept in the first snapshot's folder
        assert Path(second.path).parent.parent.name in lines[1] and "shared" in lines[1]
        assert re.search(r"[1-9]\d* file\(s\) in earlier folders", lines[1]), lines[1]
        assert "news (2 snapshot(s))" in result.output and "never by hand" in result.output
        # One pipeline, and none
        one = CliRunner().invoke(main, ["store", "ls", "news"]).output
        assert sum(1 for line in one.splitlines() if line.startswith("  20") and "  shared " in line) == 1
        assert "No snapshot of other." in CliRunner().invoke(main, ["store", "ls", "other"]).output

    def test_an_empty_store(self, store):
        result = CliRunner().invoke(main, ["store", "ls"])
        assert result.exit_code == 0 and "No snapshots." in result.output


class TestTheGcReminder:
    def test_after_a_snapshot_when_gc_would_clear_one(self, news, store, monkeypatch):
        snapshot.make(news, store=store, made_at="2026-01-01T00:00:00.000000Z")  # old, and soon not the newest
        _write_year(news, 2024, [3])
        snapshot.make(news, store=store)
        _write_year(news, 2025, [4])
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(news)])
        assert result.exit_code == 0, result.output
        assert "Snapshot made" in result.output
        assert "`chartbook store gc` would clear 1 snapshot(s), freeing" in result.output
        assert "Nothing is removed unless you ask" in result.output
        assert (store.root / "pipelines" / "news").is_dir() and len(list(store.all_snapshot_files())) == 3  # said, not done

    def test_silenced_and_quiet_when_there_is_nothing_to_clear(self, news, store):
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(news)])
        assert result.exit_code == 0 and "store gc" not in result.output  # one snapshot, the newest: nothing to clear
        _write_year(news, 2024, [3])
        snapshot.make(news, store=store, made_at="2026-01-01T00:00:00.000000Z")
        _write_year(news, 2025, [4])
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(news), "--no-gc-reminder"])
        assert result.exit_code == 0 and "store gc" not in result.output

    def test_store_info_says_it_too(self, news, store):
        snapshot.make(news, store=store, made_at="2026-01-01T00:00:00.000000Z")
        _write_year(news, 2024, [3])
        snapshot.make(news, store=store)
        result = CliRunner().invoke(main, ["store", "info"])
        assert result.exit_code == 0, result.output
        assert "`chartbook store gc` would clear 1 snapshot(s), freeing" in result.output
