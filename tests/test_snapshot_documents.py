"""A snapshot holds the index of its version and the files a writer needs, so a version's site
can be built from the store alone (docs_src/design/versioned-catalog.md, step 1)."""

import dataclasses
import json
import shutil
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import hashing, index, lock, snapshot
from chartbook.cli import main
from chartbook.store import default_store
from tests.test_model_versions import _git

MANIFEST = {
    "project": {"id": "acme/rates", "name": "Rates"},
    "dataframes": {
        "treasury": {"path": "./_data/treasury.parquet", "docs_path": "./docs_src/treasury.md"},
        "by_year": {"path": "./_data/by_year/**/*.parquet", "docs": "Partitioned by year."},
    },
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "The curve."}},
    "notes": {"method": {"path": "./docs_src/method.md"}},
    "models": {"ar1": {"path": "./_models/ar1", "trained_on": ["treasury"], "docs": "A model."}},
}


@pytest.fixture
def pipeline(tmp_path):
    """A pipeline in its own repository: data, a write-up, a note, site pages, a model; built and committed.

    Two files are in the folder and ignored by git, a `.env` and a draft site page: neither
    may reach the store.
    """
    work = tmp_path.resolve() / "rates"
    (work / "docs_src" / "site").mkdir(parents=True)
    (work / "chartbook.toml").write_text(tomli_w.dumps(MANIFEST))
    (work / "README.md").write_text("# Rates\n\nThe README of the rates pipeline.\n")
    (work / "docs_src" / "treasury.md").write_text("The treasury write-up, as it stood at this commit.\n")
    (work / "docs_src" / "method.md").write_text("# Method\n\nHow the rates are made.\n")
    (work / "docs_src" / "site" / "guide.md").write_text("# A Guide\n\nRead this first.\n")
    (work / "docs_src" / "site" / "logo-small.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    (work / "docs_src" / "site" / "draft.md").write_text("# Draft\n\nNot for anyone yet.\n")
    (work / ".env").write_text("FAKE_SECRET=do-not-store-me\n")
    (work / ".gitignore").write_text(".env\ndocs_src/site/draft.md\n_data/\n_output/\n_models/\n_docs*/\ndocs/\nchartbook.lock\n")
    (work / "_data" / "by_year" / "year=2024").mkdir(parents=True)
    pl.DataFrame({"date": ["2024-01-02", "2024-01-03"], "rate": [4.1, 4.2]}).write_parquet(work / "_data" / "treasury.parquet")
    pl.DataFrame({"rate": [4.1]}).write_parquet(work / "_data" / "by_year" / "year=2024" / "part-0.parquet")
    (work / "_output").mkdir()
    (work / "_output" / "curve.html").write_text("<html><body>curve</body></html>")
    (work / "_models" / "ar1" / "weights").mkdir(parents=True)
    (work / "_models" / "ar1" / "config.json").write_text("{}")
    (work / "_models" / "ar1" / "weights" / "best.pt").write_bytes(b"w" * 10)
    _git(work, "init", "--quiet", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "commit", "--quiet", "-m", "Work")
    return work


class TestTheIndexOfTheVersion:
    def test_the_snapshot_carries_its_index_published(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        held = Path(default_store().get(taken.index["content_hash"]))
        text = (held / snapshot.INDEX_FILE).read_text()
        built = json.loads(text)
        jsonschema.validate(built, json.loads(index.schema_path("index").read_text()))
        assert "resolved_path" not in text and str(pipeline) not in text  # nothing of this machine
        records = {record["id"]: record for record in built["records"]}
        assert [c["name"] for c in records["acme/rates:treasury"]["columns"]] == ["date", "rate"]
        assert records["acme/rates:treasury"]["docs"]["path"] == "./docs_src/treasury.md"
        assert records["acme/rates:treasury"]["content_hash"] == taken.assets["treasury"]["content_hash"]
        assert taken.index["size_bytes"] == len(text.encode())

    def test_the_record_validates_and_reads_back(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        document = json.loads(taken.path.read_text())
        jsonschema.validate(document, json.loads(snapshot.schema_path().read_text()))
        again = snapshot.read(taken.path)
        assert again.index == taken.index and again.documents == taken.documents
        assert again.hashes() == taken.hashes() == taken.asset_hashes() | {taken.index["content_hash"], taken.documents["content_hash"]}

    def test_a_manifest_a_docs_build_refuses_still_snapshots(self, pipeline):
        broken = dict(MANIFEST, charts={"curve": {"path": "./_output/curve.html", "docs": "No dataframe."}})
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(broken))
        _git(pipeline, "commit", "--quiet", "-am", "A chart with no dataframe")
        report = snapshot.make(pipeline)
        assert report.made and report.snapshot.index is None
        assert "has no 'dataframe' key" in report.index_skipped and not report.index_skipped.endswith(".")
        assert report.snapshot.documents is not None  # read from the manifest's text
        assert report.snapshot.content()["treasury"]

    def test_the_command_says_when_the_index_is_not_recorded(self, pipeline, monkeypatch):
        broken = dict(MANIFEST, charts={"curve": {"path": "./_output/curve.html", "docs": "No dataframe."}})
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(broken))
        _git(pipeline, "commit", "--quiet", "-am", "A chart with no dataframe")
        monkeypatch.chdir(pipeline)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 0, result.output
        assert "  index not recorded: Chart 'curve' has no 'dataframe' key" in result.output

    def test_a_snapshot_made_before_documents_is_made_again(self, pipeline):
        first = snapshot.make(pipeline).snapshot
        store = default_store()
        # As a snapshot made by an earlier ChartBook would read: no index, no documents
        store.remove_snapshot(first.path)
        old = dataclasses.replace(first, index=None, documents=None, path=None)
        snapshot._write(old, store)
        report = snapshot.make(pipeline)
        assert report.made and report.snapshot.documents is not None
        assert snapshot.make(pipeline).made is False  # and then not again


class TestTheDocuments:
    def test_they_are_the_tracked_files_a_writer_needs(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        assert taken.documents["files"] == [
            "README.md",
            "chartbook.toml",
            "docs_src/site/guide.md",
            "docs_src/site/logo-small.png",
            "docs_src/treasury.md",
        ]
        # The note is an asset, held as one; the ignored files are nowhere
        assert taken.assets["note/method"]["content_hash"]

    def test_nothing_ignored_reaches_the_store(self, pipeline):
        snapshot.make(pipeline)
        root = Path(str(default_store()))
        for file in root.rglob("*"):
            if file.is_file():
                data = file.read_bytes()
                assert b"do-not-store-me" not in data, file
                assert b"Not for anyone yet" not in data, file

    def test_a_path_outside_the_folder_is_not_taken(self, pipeline):
        outside = pipeline.parent / "elsewhere.md"
        outside.write_text("outside\n")
        manifest = dict(MANIFEST)
        manifest["dataframes"] = dict(MANIFEST["dataframes"])
        manifest["dataframes"]["treasury"] = dict(MANIFEST["dataframes"]["treasury"], docs_path="../elsewhere.md")
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        _git(pipeline, "commit", "--quiet", "-am", "A write-up outside")
        paths = snapshot.document_paths(pipeline)
        assert "../elsewhere.md" not in paths and all(not p.startswith("..") for p in paths)

    def test_the_lockfile_is_taken_when_git_tracks_it(self, pipeline):
        (pipeline / ".gitignore").write_text(".env\ndocs_src/site/draft.md\n_data/\n_output/\n_models/\n_docs*/\ndocs/\n")
        (pipeline / "chartbook.lock").write_text('schema = "chartbook/lock/v1"\n')
        _git(pipeline, "add", "-A")
        _git(pipeline, "commit", "--quiet", "-m", "Commit the lockfile")
        assert "chartbook.lock" in snapshot.document_paths(pipeline)

    def test_gc_keeps_them_with_the_snapshot(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        store = default_store()
        plan = lock.plan_gc(store, recent_seconds=0)
        assert plan.delete == []
        assert store.has(taken.index["content_hash"]) and store.has(taken.documents["content_hash"])


class TestLayingAVersionOut:
    def test_every_asset_is_where_its_manifest_says_with_the_same_hash(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        laid = snapshot.materialize(taken, tmp_path / "v1")
        assert laid.left_out == [] and sorted(laid.documents) == taken.documents["files"]
        for record in taken.assets.values():
            declared = record["location"]["path"]
            assert hashing.hash_path(str(laid.folder / declared)).content_hash == record["content_hash"], record["id"]
        assert (laid.folder / "docs_src" / "treasury.md").read_text().startswith("The treasury write-up")
        assert not (laid.folder / ".env").exists() and not (laid.folder / "docs_src" / "site" / "draft.md").exists()

    def test_a_site_is_built_from_the_store_alone(self, pipeline, tmp_path, monkeypatch):
        taken = snapshot.make(pipeline).snapshot
        shutil.rmtree(pipeline)  # the repository is gone; the store is all there is
        laid = snapshot.materialize(taken, tmp_path / "v1")
        monkeypatch.chdir(laid.folder)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        site = laid.folder / "docs"
        page = (site / "cb" / "dataframes" / "acme--rates" / "treasury.html").read_text()
        assert "The treasury write-up, as it stood at this commit." in page
        assert (site / "guide.html").is_file() and (site / "cb" / "method.html").is_file()
        assert (site / "cb" / "models" / "acme--rates" / "ar1.html").is_file()

    def test_what_cannot_be_laid_out_is_said(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        with pytest.raises(snapshot.SnapshotError, match="carries no documents: it was made before snapshots did"):
            snapshot.materialize(dataclasses.replace(taken, documents=None), tmp_path / "old")
        (tmp_path / "busy").mkdir()
        (tmp_path / "busy" / "x").write_text("x")
        with pytest.raises(snapshot.SnapshotError, match="has something in it"):
            snapshot.materialize(taken, tmp_path / "busy")
        assets = dict(taken.assets)
        assets["treasury"] = dict(assets["treasury"], location={"kind": "file", "path": "../../escape.parquet"})
        assets.pop("note/method")
        laid = snapshot.materialize(dataclasses.replace(taken, assets=assets), tmp_path / "v2")
        assert ("acme/rates:treasury", "its path ../../escape.parquet is outside the pipeline's folder") in laid.left_out
        assert not (tmp_path / "escape.parquet").exists()
