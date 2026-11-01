"""A version of a dataset whose files the store keeps in several snapshot folders is read where they are.

The store keeps each file once, usually in the first snapshot that had it, so a
dataset that grew by a year between two snapshots has its files in two
folders. Nothing gathers them into one folder on this machine: readers
take the list of files (``docs_src/design/plan-data-reads.md``).
"""

import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, config, data, lock, snapshot
from chartbook.cli import main
from chartbook.errors import NoSinglePathError
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return FolderStore(work / "store")


@pytest.fixture
def cache(work, monkeypatch):
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return work / "cache"


def _write_year(folder: Path, year: int, values: list) -> None:
    part = folder / "_data" / "articles" / f"year={year}"
    part.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"n": values}).write_parquet(part / "part-0.parquet")
    # And a folder of TSV files, one a year, told apart from CSV by their names
    log = folder / "_data" / "log"
    log.mkdir(parents=True, exist_ok=True)
    (log / f"part-{year}.tsv").write_text("n\tm\n" + "".join(f"{n}\t{n * 10}\n" for n in values), encoding="utf-8", newline="\n")


@pytest.fixture
def grown(work, store, cache):
    """An upstream whose Hive dataset grew by a year between two snapshots, and a downstream pinned to the second."""
    news = work / "news"
    news.mkdir()
    (news / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "news"},
            "dataframes": {
                "articles": {"path": "./_data/articles", "docs": "d"},
                "log": {"path": "./_data/log", "format": "csv", "docs": "d"},
            },
        }),
        encoding="utf-8", newline="\n",
    )
    _write_year(news, 2023, [1, 2])
    commit_pipeline(news)
    first = snapshot.make(news, store=store).snapshot
    _write_year(news, 2024, [3])
    second = snapshot.make(news, store=store).snapshot
    assert second.path != first.path
    forecast = work / "forecast"
    forecast.mkdir()
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "forecast"}, "dependencies": {"acme/news": {"path": "../news"}}}),
        encoding="utf-8", newline="\n",
    )
    assert lock.pin(forecast, store).problems == []
    return news, forecast, first, second


def _snapshot_folder(taken) -> Path:
    return Path(taken.path).parent.parent


class TestADatasetSpreadOverTwoSnapshots:
    def test_the_store_keeps_the_first_year_in_the_first_snapshots_folder(self, grown, store):
        news, forecast, first, second = grown
        kept = store.files(second.assets["articles"]["content_hash"])
        assert [f.relative for f in kept.files] == ["year=2023/part-0.parquet", "year=2024/part-0.parquet"]
        assert kept.files[0].location == _snapshot_folder(first) / "_data" / "articles" / "year=2023" / "part-0.parquet"
        assert kept.files[1].location == _snapshot_folder(second) / "_data" / "articles" / "year=2024" / "part-0.parquet"
        assert kept.home == _snapshot_folder(second) / "_data" / "articles" and not kept.in_place()
        assert not (_snapshot_folder(second) / "_data" / "articles" / "year=2023").exists()  # kept once

    def test_load_reads_both_years_with_the_hive_key(self, grown):
        news, forecast, first, second = grown
        frame = data.load("news:articles", project_dir=forecast).collect()
        assert sorted(zip(frame["year"].to_list(), frame["n"].to_list())) == [(2023, 1), (2023, 2), (2024, 3)]
        eager = data.load("news:articles", format="polars_eager", project_dir=forecast)
        assert eager.shape == (3, 2)
        pandas = data.load("news:articles", format="pandas", project_dir=forecast)
        assert sorted(pandas["n"].tolist()) == [1, 2, 3] and "year" in pandas.columns

    def test_sql_reads_both_years_with_the_hive_key(self, grown):
        news, forecast, first, second = grown
        counted = data.sql(
            "select year, count(*) as n from {news:articles} group by year order by year", project_dir=forecast
        ).collect()
        assert counted["year"].to_list() == [2023, 2024] and counted["n"].to_list() == [2, 1]
        assert data.ref("news:articles", project_dir=forecast).startswith("read_parquet([")

    def test_a_folder_of_tsv_files_is_read_as_tsv_wherever_each_is_kept(self, grown, store):
        news, forecast, first, second = grown
        kept = store.files(second.assets["log"]["content_hash"])
        assert [f.relative for f in kept.files] == ["part-2023.tsv", "part-2024.tsv"] and not kept.in_place()
        frame = data.load("news:log", project_dir=forecast).collect()
        assert frame.columns == ["n", "m"] and sorted(frame["m"].to_list()) == [10, 20, 30]
        counted = data.sql("select count(*) as n from {news:log}", project_dir=forecast).collect()
        assert counted["n"].to_list() == [3]

    def test_get_data_path_has_no_one_folder_to_give_either(self, grown):
        news, forecast, first, second = grown
        with pytest.raises(NoSinglePathError, match="'news:articles' is a dataset of 2 files, kept in 2 places"):
            data.get_data_path("news", "articles", project_dir=forecast)

    def test_the_glimpses_report_reads_every_file(self, grown):
        from chartbook.create_data_glimpses import get_dataset_report
        from chartbook.resolve import resolve

        news, forecast, first, second = grown
        location = resolve("news:articles", start_dirs=[forecast])
        report = get_dataset_report(location.path, files=location.files, listed=location.listed, inside=location.inside)
        assert "error" not in report, report
        assert report["n_rows"] == 3 and report["file_type"] == "PARQUET"
        assert report["file_size_bytes"] == sum(Path(where).stat().st_size for where in location.inside.values())

    def test_files_lists_each_where_it_is_kept(self, grown, store):
        news, forecast, first, second = grown
        found = data.files("news:articles", project_dir=forecast)
        assert found == [f.location for f in store.files(second.assets["articles"]["content_hash"]).files]
        assert {p.parents[3] for p in found} == {_snapshot_folder(first), _snapshot_folder(second)}
        assert assets.files("news:articles", project_dir=forecast) == found
        table = assets.index("news:articles", project_dir=forecast).collect()
        assert table["path"].to_list() == [str(p) for p in found] and table["year"].to_list() == ["2023", "2024"]

    def test_path_has_no_one_folder_to_give(self, grown, monkeypatch):
        news, forecast, first, second = grown
        with pytest.raises(NoSinglePathError, match="is a dataset of 2 files, kept in 2 places in the store, so there is no one folder") as e:
            data.path("news:articles", project_dir=forecast)
        assert "data.load('news:articles')" in str(e.value) and "data.files('news:articles')" in str(e.value)
        with pytest.raises(NoSinglePathError):
            assets.path("news:articles", project_dir=forecast)
        # The pipeline's own folder is a path, as before: it is where the files are written
        assert data.path("articles", project_dir=news) == news / "_data" / "articles"
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["path", "news:articles"])
        assert result.exit_code == 1 and "chartbook path news:articles --files" in result.output
        result = CliRunner().invoke(main, ["path", "news:articles", "--files"])
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [str(p) for p in data.files("news:articles", project_dir=forecast)]

    def test_nothing_is_written_to_the_cache(self, grown, cache):
        news, forecast, first, second = grown
        data.load("news:articles", project_dir=forecast).collect()
        data.sql("select count(*) from {news:articles}", project_dir=forecast).collect()
        data.files("news:articles", project_dir=forecast)
        assert not (cache / "views").exists()
        written = [p for p in cache.rglob("*") if p.is_file()] if cache.exists() else []
        assert not any(p.suffix == ".parquet" for p in written), written

    def test_a_version_is_laid_out_from_both_folders(self, grown, store, work):
        news, forecast, first, second = grown
        laid = snapshot.materialize(second, work / "laid", store)
        assert (work / "laid" / "_data" / "articles" / "year=2023" / "part-0.parquet").read_bytes() == (
            _snapshot_folder(first) / "_data" / "articles" / "year=2023" / "part-0.parquet"
        ).read_bytes()
        assert (work / "laid" / "_data" / "articles" / "year=2024" / "part-0.parquet").is_file()
        assert laid.left_out == []

    def test_restore_puts_both_years_back(self, grown, store):
        import shutil

        news, forecast, first, second = grown
        shutil.rmtree(news / "_data" / "articles")
        report = snapshot.restore(news, ["articles"], store)
        assert [name for name, *_ in report.put_back] == ["articles"] and report.left == []
        assert pl.read_parquet(news / "_data" / "articles", hive_partitioning=True).shape == (3, 2)

    def test_copying_to_another_store_carries_every_file(self, grown, store, work):
        from chartbook.transfer import copy_snapshot

        news, forecast, first, second = grown
        target = FolderStore(work / "other")
        copy_snapshot(second, store, target)
        content_hash = second.assets["articles"]["content_hash"]
        assert {f.relative: f.location.read_bytes() for f in target.files(content_hash).files} == {
            f.relative: f.location.read_bytes() for f in store.files(content_hash).files
        }
        assert target.verify() == []


class TestAFileKeptUnderItsHash:
    """A bucket's cache keeps a file under its hash, with no ending: what its name tells is told by its path inside the asset."""

    def test_a_tsv_is_read_with_tabs(self, tmp_path):
        from chartbook import formats
        from chartbook.resolve import FileLocation

        kept = tmp_path / "files" / "ab" / "cdef0123"
        kept.parent.mkdir(parents=True)
        kept.write_text("n\tm\n1\t10\n", encoding="utf-8", newline="\n")
        location = FileLocation(kept, format="csv", inside={"log.tsv": kept})
        assert formats.scan_location(location).collect().columns == ["n", "m"]
        assert "delim = '\t'" in formats.sql(location)
        # Under its own name, as before
        plain = tmp_path / "log.tsv"
        plain.write_text("n\tm\n1\t10\n", encoding="utf-8", newline="\n")
        assert formats.scan(plain).collect().columns == ["n", "m"]


class TestTheOldViewsFolderGoes:
    def test_the_first_command_removes_what_0_4_gathered_and_says_so(self, work, cache, monkeypatch):
        view = cache / "views" / ("0" * 64) / "year=2023"
        view.mkdir(parents=True)
        (view / "part-0.parquet").write_bytes(b"gathered")
        os.chmod(view / "part-0.parquet", stat.S_IRUSR)  # read-only, as a view's files were
        (cache / "hashes").mkdir()
        (cache / "hashes" / "x.json").write_text("{}", encoding="utf-8", newline="\n")
        folder = work / "pipeline"
        folder.mkdir()
        (folder / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "p"}, "dataframes": {"x": {"path": "./x.parquet", "docs": "d"}}}), encoding="utf-8", newline="\n")
        result = CliRunner().invoke(main, ["path", "x", "--project-dir", str(folder)])
        assert result.exit_code == 0, result.output
        assert not (cache / "views").exists() and (cache / "hashes" / "x.json").is_file()
        assert "Removed" in result.output and "views" in result.output and "reads files where the store keeps them" in result.output
        # Once: the next command has nothing to say, and a views folder a 0.4 install
        # beside this one gathers again is left to it
        assert (cache / ".views-removed").is_file()
        view.mkdir(parents=True)
        (view / "part-0.parquet").write_bytes(b"gathered again")
        result = CliRunner().invoke(main, ["path", "x", "--project-dir", str(folder)])
        assert "Removed" not in result.output and (view / "part-0.parquet").is_file()
