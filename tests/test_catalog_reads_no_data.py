"""A version rendered for a catalog is built from its snapshot's index, documents and charts: no data is laid out or read.

The index records, when it describes a dataframe's file, what its page
shows of the data: the glimpse and the last dates, and a files asset's
text preview. A version laid out from the store without its data takes
those from the snapshot's own index (``docs_src/design/plan-data-reads.md``,
step 2).
"""

import json
import os
from datetime import date
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w

from chartbook import config, index, snapshot, versions
from chartbook.manifest import load_manifest
from chartbook.store import FolderStore
from tests.fixtures import _git, commit_pipeline


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return FolderStore(work / "store")


@pytest.fixture
def described(work, store):
    """A pipeline with a dated dataframe and a files asset, snapshotted."""
    folder = work / "rates"
    (folder / "_data" / "notes").mkdir(parents=True)
    pl.DataFrame({
        "date": [date(2024, 1, 1), date(2024, 6, 30)],
        "DGS10": [4.0, None],
        "DGS2": [4.5, 4.4],
    }).write_parquet(folder / "_data" / "rates.parquet")
    (folder / "_data" / "notes" / "readme.txt").write_text("first line\nsecond line\n", encoding="utf-8", newline="\n")
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "rates", "name": "Rates"},
            "dataframes": {"rates": {"path": "./_data/rates.parquet", "date_col": "date", "docs": "Daily rates."}},
            "files": {"notes": {"path": "./_data/notes", "docs": "Notes."}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text("# Rates\n\nA pipeline.\n", encoding="utf-8", newline="\n")
    # The README is a document of the version: committed, as a real pipeline's is
    (folder / ".gitignore").write_text("/*\n!/chartbook.toml\n!/.gitignore\n!/README.md\n", encoding="utf-8", newline="\n")
    _git(folder, "init", "--quiet", "-b", "main")
    commit_pipeline(folder)
    taken = snapshot.make(folder, store=store).snapshot
    return folder, taken


def _records(folder: Path) -> dict:
    return {r["id"]: r for r in index.build_index(load_manifest(base_dir=folder))["records"]}


class TestTheIndexRecordsWhatAPageShows:
    def test_a_dataframes_glimpse_and_last_dates(self, described):
        folder, taken = described
        rates = _records(folder)["rates:rates"]
        assert rates["glimpse"].startswith("Rows: 2") and "DGS10" in rates["glimpse"]
        # DGS10's last non-null date is January; DGS2's is June
        assert rates["last_dates"] == {"min": "2024-01-01 00:00:00", "max": "2024-06-30 00:00:00"}
        jsonschema.validate(rates, json.loads(index.schema_path("Dataframe").read_text(encoding="utf-8")))

    def test_a_files_assets_text_preview(self, described):
        folder, taken = described
        notes = _records(folder)["rates:file/notes"]
        assert notes["preview"]["path"] == "readme.txt" and notes["preview"]["kind"] == "text"
        assert notes["preview"]["text"].startswith("first line")
        jsonschema.validate(notes, json.loads(index.schema_path("File").read_text(encoding="utf-8")))

    def test_the_snapshot_carries_them(self, described, store):
        folder, taken = described
        stored = {r["id"]: r for r in snapshot._stored_records(taken, store)}
        assert "glimpse" in stored["rates:rates"] and "last_dates" in stored["rates:rates"]
        assert stored["rates:file/notes"]["preview"]["kind"] == "text"


class TestAVersionIsBuiltWithoutItsData:
    def test_laid_out_without_data_the_index_still_describes_every_asset(self, described, store, work):
        folder, taken = described
        laid = snapshot.materialize(taken, work / "laid", store, data=False)
        assert sorted(laid.from_index) == ["rates:file/notes", "rates:rates"] and laid.left_out == []
        assert not (work / "laid" / "_data").exists()
        assert (work / "laid" / "README.md").is_file() and (work / "laid" / "_chartbook" / "index.json").is_file()
        records = _records(work / "laid")
        rates = records["rates:rates"]
        assert rates["content_hash"] == taken.assets["rates"]["content_hash"] and rates["row_count"] == 2
        assert [c["name"] for c in rates["columns"]] == ["date", "DGS10", "DGS2"]
        assert rates["date_range"] == {"first": "2024-01-01", "last": "2024-06-30"}
        assert rates["glimpse"].startswith("Rows: 2") and rates["last_dates"]["max"] == "2024-06-30 00:00:00"
        assert {r["ref"]["part"] for r in records.values() if r["kind"] == "Series"} == {"DGS10", "DGS2"}
        notes = records["rates:file/notes"]
        assert notes["file_count"] == 1 and notes["preview"]["text"].startswith("first line")
        # Laid out whole, as restore and run --upstream want it, the data is there
        snapshot.materialize(taken, work / "whole", store)
        assert (work / "whole" / "_data" / "rates.parquet").is_file()

    def test_the_versions_site_is_built_with_the_data_gone_from_the_store(self, described, store):
        folder, taken = described
        for record in (taken.assets["rates"], taken.assets["file/notes"]):
            for file in store.files(record["content_hash"]).files:
                os.chmod(file.location, 0o600)
                file.location.unlink()
        rendered = versions.render(taken, store)
        assert rendered.built, rendered.why
        page = (rendered.folder / "cb" / "dataframes" / "rates" / "rates.html").read_text(encoding="utf-8")
        assert "DGS10" in page and "2024-06-30" in page and "Not built" not in page and "not built" not in page
        notes = (rendered.folder / "cb" / "files" / "rates" / "notes.html").read_text(encoding="utf-8")
        assert "first line" in notes and "readme.txt" in notes

    def test_a_snapshot_made_before_glimpses_were_recorded_says_so(self, described, store, work):
        """A 0.4 snapshot's index has columns, rows and dates but no glimpse: the page says so, and reads no file."""
        from chartbook.writers.sphinx import NO_GLIMPSE_RECORDED, SphinxWriter

        folder, taken = described
        snapshot.materialize(taken, work / "laid", store, data=False)
        saved = work / "laid" / "_chartbook" / "index.json"
        stored = json.loads(saved.read_text(encoding="utf-8"))
        for record in stored["records"]:
            record.pop("glimpse", None)
            record.pop("last_dates", None)
        saved.write_text(json.dumps(stored), encoding="utf-8", newline="\n")
        built = index.build_index(load_manifest(base_dir=work / "laid"))
        rates = next(r for r in built["records"] if r["id"] == "rates:rates")
        assert "glimpse" not in rates and rates["row_count"] == 2
        writer = SphinxWriter(built, theme="pipeline", docs_src_dir=work / "laid" / "_docs_src")
        page = writer.dataframe_page("rates:rates")
        assert NO_GLIMPSE_RECORDED in page and "Error reading file" not in page
        # A sentence of ours, so a paragraph: in a code block it was set in type and coloured as Python
        assert f"## DataFrame Glimpse\n\n{NO_GLIMPSE_RECORDED}\n" in page and "```" not in page.split("## DataFrame Glimpse")[1].split("##")[0]

    def test_a_recorded_glimpse_is_plain_text_in_its_fence(self, described, store, work):
        """The glimpse is the data's text: its fence says ``text`` so Sphinx does not colour it as Python."""
        from chartbook.writers.sphinx import SphinxWriter

        folder, taken = described
        snapshot.materialize(taken, work / "laid", store, data=False)
        built = index.build_index(load_manifest(base_dir=work / "laid"))
        writer = SphinxWriter(built, theme="pipeline", docs_src_dir=work / "laid" / "_docs_src")
        page = writer.dataframe_page("rates:rates")
        assert "## DataFrame Glimpse\n\n```text\n" in page and "DGS10" in page


def _laid_out_index(work: Path, taken, store, edit=None) -> Path:
    """A version laid out without its data, its stored index edited as a store anyone can write to might have it."""
    snapshot.materialize(taken, work / "laid", store, data=False)
    saved = work / "laid" / "_chartbook" / "index.json"
    if edit is not None:
        stored = json.loads(saved.read_text(encoding="utf-8"))
        edit(stored)
        saved.write_text(json.dumps(stored), encoding="utf-8", newline="\n")
    return work / "laid"


class TestWhatTheReviewFound:
    def test_a_table_in_a_source_is_shown_from_the_index_too(self, work, store):
        """A table has a definition hash, not a content hash; its parquet is not laid out either."""
        import duckdb

        from chartbook.sitefiles import not_built
        from chartbook.writers.sphinx import SphinxWriter

        folder = work / "rates"
        (folder / "_data").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "rates"},
                "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                "dataframes": {"curve": {"source": "local", "table": "curve", "docs": "A table.", "date_col": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        con = duckdb.connect(str(folder / "_data" / "local.duckdb"))
        con.sql("create table curve as select * from (values (date '2024-01-01', 1.0, 4.0), (date '2024-01-02', 1.1, 4.3)) t(d, y02, y10)")
        con.close()
        (folder / "README.md").write_text("# Rates\n", encoding="utf-8", newline="\n")
        (folder / ".gitignore").write_text("/*\n!/chartbook.toml\n!/.gitignore\n!/README.md\n", encoding="utf-8", newline="\n")
        _git(folder, "init", "--quiet", "-b", "main")
        commit_pipeline(folder)
        taken = snapshot.make(folder, store=store).snapshot
        own = _records(folder)["rates:curve"]
        assert own["glimpse"].startswith("A table curve in source 'local'") and "y02" in own["glimpse"]
        assert own["last_dates"]["min"].startswith("2024-01-01") and own["last_dates"]["max"].startswith("2024-01-02")
        assert "definition_hash" in own
        laid = _laid_out_index(work, taken, store)
        assert not (laid / "_chartbook" / "tables").exists()
        curve = _records(laid)["rates:curve"]
        assert curve["location"]["kind"] == "file" and curve["location"]["path"] == "_chartbook/tables/curve.parquet"
        assert [c["name"] for c in curve["columns"]] == ["d", "y02", "y10"] and curve["row_count"] == 2
        assert curve["glimpse"] == own["glimpse"] and curve["definition_hash"] == own["definition_hash"]
        assert not not_built(curve)
        rendered = versions.render(taken, store)
        assert rendered.built, rendered.why
        page = (rendered.folder / "cb" / "dataframes" / "rates" / "curve.html").read_text(encoding="utf-8")
        assert "y02" in page and "2024-01-02" in page and "Not built" not in page and "not built" not in page

    def test_an_index_not_whole_in_the_store_is_tried_again_later(self, described, store, work):
        folder, taken = described
        held = store.files(taken.index["content_hash"], name="index.json").one.location
        os.chmod(held, 0o600)
        held.write_bytes(held.read_bytes()[:-20])  # a sync that has not finished
        with pytest.raises(snapshot.StoreNotReadyError, match="not fully synced yet"):
            snapshot.materialize(taken, work / "laid", store, data=False)
        held.unlink()
        with pytest.raises(snapshot.StoreNotReadyError):
            snapshot.materialize(taken, work / "laid-2", store, data=False)

    def test_a_malformed_stored_record_is_passed_over_not_crashed_on(self, described, store, work):
        folder, taken = described

        def spoil(stored):
            for record in stored["records"]:
                if record["id"] == "rates:rates":
                    record["columns"] = ["date"]
                    record["row_count"] = "2"
                    record["last_dates"] = {"min": "<img src=x>", "max": "2024-06-30 00:00:00"}
                    record["glimpse"] = 7
                if record["id"] == "rates:file/notes":
                    record["preview"] = {"path": "../../etc/passwd", "kind": "text", "text": "x"}
                    record["files"] = [{"path": "readme.txt"}]

        laid = _laid_out_index(work, taken, store, spoil)
        records = _records(laid)
        rates = records["rates:rates"]
        assert rates["content_hash"] == taken.assets["rates"]["content_hash"]
        assert "columns" not in rates and "row_count" not in rates and "last_dates" not in rates and "glimpse" not in rates
        notes = records["rates:file/notes"]
        assert "preview" not in notes and "files" not in notes and notes["file_count"] == 1

    @pytest.mark.parametrize("columns", [[1], [{"name": ["x"], "dtype": "Int64"}], [{"name": "date"}]])
    def test_stored_columns_of_the_wrong_shape_are_passed_over_with_a_good_row_count(self, described, store, work, columns):
        """The fallback to the stored facts checks their shape as every other read of them does (found reviewing 0.5.0)."""
        folder, taken = described

        def spoil(stored):
            for record in stored["records"]:
                if record["id"] == "rates:rates":
                    record["columns"] = columns
                    record["row_count"] = 3

        records = _records(_laid_out_index(work, taken, store, spoil))
        assert "columns" not in records["rates:rates"]  # and the build did not stop on them

    def test_a_folder_of_parts_has_no_last_dates_and_a_csvs_text_dates_are_read(self, work, store):
        from chartbook.utils import GLIMPSE_MAX_CHARS

        folder = work / "mixed"
        (folder / "_data" / "parts" / "year=2024").mkdir(parents=True)
        pl.DataFrame({"date": [date(2024, 1, 1)], "v": [1.0]}).write_parquet(folder / "_data" / "parts" / "year=2024" / "a.parquet")
        (folder / "_data" / "log.csv").write_text("d,n\n2024-01-01,1\n2024-03-01,\n", encoding="utf-8", newline="\n")
        pl.DataFrame({"date": [date(2024, 1, 1)], "text": ["x" * (GLIMPSE_MAX_CHARS + 5000)]}).write_parquet(folder / "_data" / "wide.parquet")
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "mixed"},
                "dataframes": {
                    "parts": {"path": "./_data/parts", "date_col": "date", "docs": "d"},
                    "log": {"path": "./_data/log.csv", "date_col": "d", "docs": "d"},
                    "wide": {"path": "./_data/wide.parquet", "docs": "d"},
                },
            }),
            encoding="utf-8", newline="\n",
        )
        records = _records(folder)
        assert records["mixed:parts"]["last_dates"] == {"min": "N/A", "max": "N/A"}  # not read whole for two dates
        assert records["mixed:log"]["last_dates"] == {"min": "2024-01-01 00:00:00", "max": "2024-01-01 00:00:00"}
        wide = records["mixed:wide"]["glimpse"]
        assert len(wide) <= GLIMPSE_MAX_CHARS + 100 and wide.endswith("characters)")

