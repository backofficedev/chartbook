"""A dataset's Hive keys come from each file's path inside it, never from where the store keeps the file.

The store keeps each file once, by its bytes: a partition's file can sit at
another partition's path (two partitions of the same bytes, as polars writes
them when it drops the key's column), and an S3 store's copy here is named by
its hash. Found reviewing 0.5.0 (2026-11-01): reads then took 2023 for 2024,
or no key at all.
"""

from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import config, data, lock, snapshot
from chartbook import store as store_module
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline


def _partition(folder: Path, year: int, values: list, fmt: str = "parquet") -> None:
    part = folder / "_data" / "articles" / f"year={year}"
    part.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame({"n": values})
    if fmt == "parquet":
        frame.write_parquet(part / "part-0.parquet")
    else:
        frame.write_ipc(part / "part-0.arrow")


def _pipelines(work: Path, fmt: str = "parquet", news_id: str = "news", dependency: dict = None) -> tuple:
    news, reader = work / "news", work / "reader"
    news.mkdir()
    reader.mkdir()
    entry = {"path": "./_data/articles", "docs": "Articles by year."}
    if fmt == "ipc":
        entry["format"] = "ipc"
    (news / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": news_id}, "dataframes": {"articles": entry}}), encoding="utf-8", newline="\n"
    )
    (reader / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "reader"}, "dependencies": dependency or {"acme/news": {"path": "../news"}}}),
        encoding="utf-8", newline="\n",
    )
    return news, reader


def _years(reader: Path) -> tuple:
    loaded = data.load("news:articles", project_dir=reader).collect()
    counted = data.sql(
        "select year, count(*) as rows from {news:articles} group by year order by year", project_dir=reader
    ).collect()
    return sorted(loaded["year"].to_list()), dict(zip(counted["year"].to_list(), counted["rows"].to_list()))


class TestOnAFolderStore:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(tmp_path.resolve() / "store"))
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(tmp_path.resolve() / "cache"))
        return FolderStore(tmp_path.resolve() / "store")

    @pytest.mark.parametrize("across", [False, True], ids=["one snapshot", "two snapshots"])
    def test_two_partitions_of_the_same_bytes_keep_their_own_keys(self, tmp_path, store, across):
        news, reader = _pipelines(tmp_path.resolve())
        _partition(news, 2023, [1, 2])
        commit_pipeline(news)
        if across:
            snapshot.make(news, store=store)
        _partition(news, 2024, [1, 2])  # the same bytes as 2023's file: kept once
        snapshot.make(news, store=store)
        assert lock.pin(reader, store).problems == []
        files = data.files("news:articles", project_dir=reader)
        assert len(files) == 2 and len(set(files)) == 1  # one file, at 2023's path, for both
        assert _years(reader) == ([2023, 2023, 2024, 2024], {2023: 2, 2024: 2})

    def test_a_dataset_whose_files_sit_at_their_own_paths_is_read_as_before(self, tmp_path, store):
        news, reader = _pipelines(tmp_path.resolve())
        _partition(news, 2023, [1, 2])
        commit_pipeline(news)
        snapshot.make(news, store=store)
        _partition(news, 2024, [3])
        snapshot.make(news, store=store)
        assert lock.pin(reader, store).problems == []
        assert _years(reader) == ([2023, 2023, 2024], {2023: 2, 2024: 1})


class TestOnAnS3Store:
    pytest.importorskip("moto")

    @pytest.fixture
    def client(self, monkeypatch):
        from tests.mocked_s3 import mocked_s3

        with mocked_s3(monkeypatch) as client:
            yield client

    @pytest.mark.parametrize("fmt", ["parquet", "ipc"])
    def test_the_keys_are_read_on_another_machine(self, tmp_path, client, monkeypatch, fmt):
        from tests.mocked_s3 import URL
        from tests.test_model_versions import _commit, _git

        work = tmp_path.resolve()
        news, reader = _pipelines(work, fmt, news_id="acme/news", dependency={"news": {"path": "../news"}})
        _partition(news, 2023, [1, 2], fmt)
        _partition(news, 2024, [3], fmt)
        _partition(news, 2025, [1, 2], fmt)  # 2023's bytes
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8", newline="\n")
        _commit(work)
        store_module._plugin_store_class.cache_clear()
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-a"))
        snapshot.make(news)
        assert {e.status for e in lock.pin(reader).events if e.asset} == {"pinned"}
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-b"))
        assert _years(reader) == ([2023, 2023, 2024, 2025, 2025], {2023: 2, 2024: 1, 2025: 2})
