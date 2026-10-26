"""A snapshot holds the index of its version and the files a writer needs, so a version's site
can be built from the store alone (docs_src/design/versioned-catalog.md, step 1)."""

import dataclasses
import json
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
from tests.fixtures import remove_tree

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
    (work / "chartbook.toml").write_text(tomli_w.dumps(MANIFEST), encoding="utf-8")
    (work / "README.md").write_text("# Rates\n\nThe README of the rates pipeline.\n", encoding="utf-8")
    (work / "docs_src" / "treasury.md").write_text("The treasury write-up, as it stood at this commit.\n", encoding="utf-8")
    (work / "docs_src" / "method.md").write_text("# Method\n\nHow the rates are made.\n", encoding="utf-8")
    (work / "docs_src" / "site" / "guide.md").write_text("# A Guide\n\nRead this first.\n", encoding="utf-8")
    (work / "docs_src" / "site" / "logo-small.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    (work / "docs_src" / "site" / "draft.md").write_text("# Draft\n\nNot for anyone yet.\n", encoding="utf-8")
    (work / ".env").write_text("FAKE_SECRET=do-not-store-me\n", encoding="utf-8")
    (work / ".gitignore").write_text(".env\ndocs_src/site/draft.md\n_data/\n_output/\n_models/\n_docs*/\ndocs/\nchartbook.lock\n", encoding="utf-8")
    (work / "_data" / "by_year" / "year=2024").mkdir(parents=True)
    pl.DataFrame({"date": ["2024-01-02", "2024-01-03"], "rate": [4.1, 4.2]}).write_parquet(work / "_data" / "treasury.parquet")
    pl.DataFrame({"rate": [4.1]}).write_parquet(work / "_data" / "by_year" / "year=2024" / "part-0.parquet")
    (work / "_output").mkdir()
    (work / "_output" / "curve.html").write_text("<html><body>curve</body></html>", encoding="utf-8")
    (work / "_models" / "ar1" / "weights").mkdir(parents=True)
    (work / "_models" / "ar1" / "config.json").write_text("{}", encoding="utf-8")
    (work / "_models" / "ar1" / "weights" / "best.pt").write_bytes(b"w" * 10)
    _git(work, "init", "--quiet", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "commit", "--quiet", "-m", "Work")
    return work


class TestTheIndexOfTheVersion:
    def test_the_snapshot_carries_its_index_published(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        held = Path(default_store().get(taken.index["content_hash"]))
        text = (held / snapshot.INDEX_FILE).read_text(encoding="utf-8")
        built = json.loads(text)
        jsonschema.validate(built, json.loads(index.schema_path("index").read_text(encoding="utf-8")))
        assert "resolved_path" not in text and str(pipeline) not in text  # nothing of this machine
        records = {record["id"]: record for record in built["records"]}
        assert [c["name"] for c in records["acme/rates:treasury"]["columns"]] == ["date", "rate"]
        assert records["acme/rates:treasury"]["docs"]["path"] == "./docs_src/treasury.md"
        assert records["acme/rates:treasury"]["content_hash"] == taken.assets["treasury"]["content_hash"]
        assert taken.index["size_bytes"] == len(text.encode())

    def test_the_record_validates_and_reads_back(self, pipeline):
        taken = snapshot.make(pipeline).snapshot
        document = json.loads(taken.path.read_text(encoding="utf-8"))
        jsonschema.validate(document, json.loads(snapshot.schema_path().read_text(encoding="utf-8")))
        again = snapshot.read(taken.path)
        assert again.index == taken.index and again.documents == taken.documents
        assert again.hashes() == taken.hashes() == taken.asset_hashes() | {taken.index["content_hash"], taken.documents["content_hash"]}

    def test_a_manifest_a_docs_build_refuses_still_snapshots(self, pipeline):
        broken = dict(MANIFEST, charts={"curve": {"path": "./_output/curve.html", "docs": "No dataframe."}})
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(broken), encoding="utf-8")
        _git(pipeline, "commit", "--quiet", "-am", "A chart with no dataframe")
        report = snapshot.make(pipeline)
        assert report.made and report.snapshot.index is None
        assert "has no 'dataframe' key" in report.index_skipped and not report.index_skipped.endswith(".")
        assert report.snapshot.documents is not None  # read from the manifest's text
        assert report.snapshot.content()["treasury"]

    def test_the_command_says_when_the_index_is_not_recorded(self, pipeline, monkeypatch):
        broken = dict(MANIFEST, charts={"curve": {"path": "./_output/curve.html", "docs": "No dataframe."}})
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(broken), encoding="utf-8")
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
        outside.write_text("outside\n", encoding="utf-8")
        manifest = dict(MANIFEST)
        manifest["dataframes"] = dict(MANIFEST["dataframes"])
        manifest["dataframes"]["treasury"] = dict(MANIFEST["dataframes"]["treasury"], docs_path="../elsewhere.md")
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
        _git(pipeline, "commit", "--quiet", "-am", "A write-up outside")
        paths, skipped = snapshot.document_paths(pipeline)
        assert "../elsewhere.md" not in paths and all(not p.startswith("..") for p in paths)
        assert ("../elsewhere.md", snapshot.NOT_A_PLAIN_PATH) in skipped

    def test_the_lockfile_is_taken_when_git_tracks_it(self, pipeline):
        (pipeline / ".gitignore").write_text(".env\ndocs_src/site/draft.md\n_data/\n_output/\n_models/\n_docs*/\ndocs/\n", encoding="utf-8")
        (pipeline / "chartbook.lock").write_text('schema = "chartbook/lock/v1"\n', encoding="utf-8")
        _git(pipeline, "add", "-A")
        _git(pipeline, "commit", "--quiet", "-m", "Commit the lockfile")
        assert "chartbook.lock" in snapshot.document_paths(pipeline)[0]

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
        assert (laid.folder / "docs_src" / "treasury.md").read_text(encoding="utf-8").startswith("The treasury write-up")
        assert not (laid.folder / ".env").exists() and not (laid.folder / "docs_src" / "site" / "draft.md").exists()

    def test_a_site_is_built_from_the_store_alone(self, pipeline, tmp_path, monkeypatch):
        taken = snapshot.make(pipeline).snapshot
        remove_tree(pipeline)  # the repository is gone; the store is all there is
        laid = snapshot.materialize(taken, tmp_path / "v1")
        monkeypatch.chdir(laid.folder)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        site = laid.folder / "docs"
        page = (site / "cb" / "dataframes" / "acme--rates" / "treasury.html").read_text(encoding="utf-8")
        assert "The treasury write-up, as it stood at this commit." in page
        assert (site / "guide.html").is_file() and (site / "cb" / "method.html").is_file()
        assert (site / "cb" / "models" / "acme--rates" / "ar1.html").is_file()

    def test_what_cannot_be_laid_out_is_said(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        with pytest.raises(snapshot.SnapshotError, match="carries no documents: it was made before snapshots did"):
            snapshot.materialize(dataclasses.replace(taken, documents=None), tmp_path / "old")
        (tmp_path / "busy").mkdir()
        (tmp_path / "busy" / "x").write_text("x", encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="has something in it"):
            snapshot.materialize(taken, tmp_path / "busy")
        assets = dict(taken.assets)
        assets["treasury"] = dict(assets["treasury"], location={"kind": "file", "path": "../../escape.parquet"})
        assets.pop("note/method")
        laid = snapshot.materialize(dataclasses.replace(taken, assets=assets), tmp_path / "v2")
        assert ("acme/rates:treasury", "its path ../../escape.parquet is not a plain path inside the pipeline's folder") in laid.left_out
        assert not (tmp_path / "escape.parquet").exists()


def _set(pipeline: Path, **changes) -> None:
    """Rewrite the manifest with changes to whole tables, commit."""
    manifest = {**MANIFEST, **changes}
    (pipeline / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
    _git(pipeline, "add", "-A")
    _git(pipeline, "commit", "--quiet", "-m", "Change")


class TestWhatTheReviewFound:
    """Each a way a manifest written to mislead, or a store record forged, reached past the folder."""

    @pytest.mark.parametrize(
        "text",
        ["/etc/passwd", "\\Windows\\x", "C:foo", "C:\\x", "../x", "a/../../x", "docs/../README.md", ".git/config",
         "docs/.GIT/hooks/x", ".git./x", ":(top)README.md", ":/", "a:b", "", "  ", ".", "./",
         ".g\u200cit/config", "\ufeff.git/x", ".gi\u206at/x", "GIT~1/config", "git~2/x", ".git::$INDEX_ALLOCATION/x"],
    )
    def test_what_is_not_a_plain_path(self, text):
        assert snapshot.safe_relative(text) is None

    @pytest.mark.parametrize(
        "text,plain",
        [("./docs_src/x.md", "docs_src/x.md"), ("docs_src\\x.md", "docs_src/x.md"), ("..hidden/x", "..hidden/x"),
         ("a/./b", "a/b"), ("report[2024].md", "report[2024].md"), (".gitignore", ".gitignore")],
    )
    def test_what_is(self, text, plain):
        assert snapshot.safe_relative(text) == plain

    def test_pathspec_magic_reaches_nothing_outside(self, pipeline, tmp_path):
        (pipeline.parent / "victim").mkdir()
        (pipeline.parent / "victim" / "target.txt").write_text("ORIGINAL", encoding="utf-8")
        _set(pipeline, project={**MANIFEST["project"], "readme": ":(top)README.md", "logo": ":/"})
        paths, skipped = snapshot.document_paths(pipeline)
        assert all(snapshot.safe_relative(p) == p for p in paths)
        assert (":(top)README.md", snapshot.NOT_A_PLAIN_PATH) in skipped
        snapshot.make(pipeline)
        assert (pipeline.parent / "victim" / "target.txt").read_text(encoding="utf-8") == "ORIGINAL"

    def test_a_tracked_link_is_never_followed(self, pipeline, tmp_path):
        outside = tmp_path / "outside-secret.md"
        outside.write_text("OUTSIDE BYTES\n", encoding="utf-8")
        (pipeline / "docs_src" / "report[2024].md").symlink_to(outside)
        (pipeline / "docs_src" / "site" / "linked.md").symlink_to(outside)
        (pipeline / "docs_src" / "sub").mkdir()
        (pipeline / "docs_src" / "sub" / ".leak").symlink_to(outside)
        dataframes = {**MANIFEST["dataframes"], "treasury": {**MANIFEST["dataframes"]["treasury"], "docs_path": "docs_src/report[2024].md"},
                      "other": {"path": "./_data/treasury.parquet", "docs_path": "docs_src/*"}}
        _set(pipeline, dataframes=dataframes)
        paths, skipped = snapshot.document_paths(pipeline)
        assert "docs_src/report[2024].md" not in paths and ("docs_src/report[2024].md", snapshot.A_LINK) in skipped
        assert ("docs_src/site/linked.md", snapshot.A_LINK) in skipped
        assert "docs_src/site/guide.md" in paths  # one bad link does not lose the rest of the site
        assert not any(p.startswith("docs_src/sub") for p in paths)
        snapshot.make(pipeline)
        for file in Path(str(default_store())).rglob("*"):
            if file.is_file():
                assert b"OUTSIDE BYTES" not in file.read_bytes(), file

    def test_the_command_says_what_was_not_kept(self, pipeline, tmp_path, monkeypatch):
        (pipeline / "docs_src" / "site" / "linked.md").symlink_to(tmp_path)
        _git(pipeline, "add", "-A")
        _git(pipeline, "commit", "--quiet", "-m", "A link")
        monkeypatch.chdir(pipeline)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 0, result.output
        assert f"  document not kept: docs_src/site/linked.md ({snapshot.A_LINK})" in result.output

    def test_a_forged_record_cannot_plant_git_or_climb_out(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        store = default_store()
        forged = tmp_path / "forged"
        (forged / ".git").mkdir(parents=True)
        (forged / ".git" / "config").write_text("[core]\n\tfsmonitor = touch PWNED\n", encoding="utf-8")
        (forged / "README.md").write_text("# forged\n", encoding="utf-8")
        (forged / ".chartbook-version.json").write_text('{"pipeline": "evil/other"}', encoding="utf-8")
        stored = store.put(forged)
        files = [".git/config", "README.md", "../escape.md", "C:evil.md", ".chartbook-version.json", ".g\u200cit/config"]
        bad = dataclasses.replace(taken, documents={"content_hash": stored.content_hash, "files": files})
        laid = snapshot.materialize(bad, tmp_path / "laid")
        assert not (laid.folder / ".git").exists() and (laid.folder / "README.md").is_file()
        assert {path for path, _ in laid.left_out} >= {".git/config", "../escape.md", "C:evil.md", ".chartbook-version.json"}
        assert not (tmp_path / "escape.md").exists()
        # The version file is ChartBook's, written first, whatever the record says
        assert json.loads((laid.folder / ".chartbook-version.json").read_text(encoding="utf-8"))["pipeline"] == "acme/rates"

    def test_a_git_folder_a_filesystem_makes_of_a_name_is_removed_and_refused(self, pipeline, tmp_path, monkeypatch):
        """HFS+ drops invisible code points, so a name that is not `.git` becomes one on disk.
        Should a filesystem do that with a name the rule misses, the last check finds it."""
        taken = snapshot.make(pipeline).snapshot
        store = default_store()
        forged = tmp_path / "forged"
        (forged / ".git").mkdir(parents=True)
        (forged / ".git" / "config").write_text("[core]\n\tfsmonitor = touch PWNED\n", encoding="utf-8")
        stored = store.put(forged)
        monkeypatch.setattr(snapshot, "_is_dot_git", lambda part: False)  # as if the rule missed this alias
        bad = dataclasses.replace(taken, documents={"content_hash": stored.content_hash, "files": [".git/config"]})
        with pytest.raises(snapshot.SnapshotError, match="made a .git in"):
            snapshot.materialize(bad, tmp_path / "laid")
        assert not (tmp_path / "laid" / ".git").exists()

    def test_odd_records_and_manifests_do_not_crash_a_layout(self, pipeline, tmp_path):
        models = {"ar1": {**MANIFEST["models"]["ar1"], "metrics_path": "chartbook.toml/x"}}
        _set(pipeline, models=models, project={**MANIFEST["project"], "site_dir": ".chartbook-version.json"})
        (pipeline / "_output").mkdir(exist_ok=True)
        taken = snapshot.make(pipeline).snapshot
        taken = dataclasses.replace(taken, assets={**taken.assets, "model/ar1": {**taken.assets["model/ar1"], "metrics": {"rmse": 1}}})
        laid = snapshot.materialize(taken, tmp_path / "laid")
        assert ("model/ar1", "its scores could not be written to chartbook.toml/x") in laid.left_out
        assert (laid.folder / ".chartbook-version.json").is_file()
        with pytest.raises(snapshot.SnapshotError, match="not a hash"):
            snapshot.materialize(dataclasses.replace(taken, documents={"content_hash": "nonsense", "files": []}), tmp_path / "bad")

    def test_a_version_file_is_read_only_where_it_belongs(self, pipeline, tmp_path):
        from chartbook.identity import VERSION_FILE, derive_pipeline_id, read_version_file

        laid = snapshot.materialize(snapshot.make(pipeline).snapshot, tmp_path / "laid")
        assert read_version_file(laid.folder)["pipeline"] == "acme/rates"
        assert derive_pipeline_id({"id": "explicit/wins"}, laid.folder) == "explicit/wins"
        # Copied into a repository and committed, the folder is a new pipeline, not the old version
        _git(laid.folder, "init", "--quiet", "-b", "main")
        assert read_version_file(laid.folder) == {}
        remove_tree(laid.folder / ".git")
        (laid.folder / VERSION_FILE).write_text("[" * 200000, encoding="utf-8")
        assert read_version_file(laid.folder) == {}
        (laid.folder / VERSION_FILE).write_text(json.dumps({"pipeline": "x", "pad": "y" * 100000}), encoding="utf-8")
        assert read_version_file(laid.folder) == {}  # too large to be one

    def test_a_link_planted_in_an_object_is_not_followed(self, pipeline, tmp_path):
        """A store a team shares may hold whatever someone put there: a link in a directory
        asset's object, in a one-file asset's object, and in the documents' object."""
        taken = snapshot.make(pipeline).snapshot
        store = default_store()
        secret = tmp_path / "secret.txt"
        secret.write_text("LOCAL SECRET", encoding="utf-8")
        model = Path(store.get(taken.assets["model/ar1"]["content_hash"]))
        (model / "weights" / "planted").symlink_to(secret)
        treasury = Path(store.get(taken.assets["treasury"]["content_hash"]))
        (treasury / "treasury.parquet").chmod(0o644)
        (treasury / "treasury.parquet").unlink()
        (treasury / "treasury.parquet").symlink_to(secret)
        documents = Path(store.get(taken.documents["content_hash"]))
        (documents / "README.md").chmod(0o644)
        (documents / "README.md").unlink()
        (documents / "README.md").symlink_to(secret)
        laid = snapshot.materialize(taken, tmp_path / "laid")
        assert not (laid.folder / "_models" / "ar1" / "weights" / "planted").exists()
        assert not (laid.folder / "README.md").exists() and ("README.md", snapshot.A_LINK) in laid.left_out
        assert ("acme/rates:treasury", "its object holds no file") in laid.left_out
        assert "LOCAL SECRET" not in "".join(p.read_text(errors="replace", encoding="utf-8") for p in laid.folder.rglob("*") if p.is_file())

    def test_an_object_folder_that_is_a_link_is_refused(self, pipeline, tmp_path):
        from chartbook.store import StoreError

        taken = snapshot.make(pipeline).snapshot
        store = default_store()
        mine = tmp_path / "mine"
        (mine / "docs_src" / "site").mkdir(parents=True)
        (mine / "docs_src" / "site" / "private.md").write_text("MY PRIVATE NOTES", encoding="utf-8")
        held = Path(store.get(taken.documents["content_hash"]))
        import shutil

        for file in held.rglob("*"):
            file.chmod(0o755 if file.is_dir() else 0o644)
        remove_tree(held)
        held.symlink_to(mine)
        with pytest.raises(StoreError, match="is a link, or leads out of the store"):
            store.get(taken.documents["content_hash"])
        with pytest.raises(StoreError):
            snapshot.materialize(taken, tmp_path / "laid")
        assert not any("MY PRIVATE NOTES" in p.read_text(errors="replace", encoding="utf-8") for p in (tmp_path / "laid").rglob("*") if p.is_file())

    def test_a_tracked_name_that_differs_from_its_plain_form_is_not_taken(self, pipeline):
        """A tracked decoy, `secret.env ` with a trailing space or `private\\key.env`, put in
        order, names another file, an ignored one; git's names are taken exactly or not at all."""
        site = pipeline / "docs_src" / "site"
        (site / "secret.env").write_text("IGNORED SECRET", encoding="utf-8")
        (site / "secret.env ").write_text("decoy", encoding="utf-8")
        (site / "private").mkdir()
        (site / "private" / "key.env").write_text("IGNORED SECRET", encoding="utf-8")
        (site / "private\\key.env").write_text("decoy", encoding="utf-8")
        with open(pipeline / ".gitignore", "a", encoding="utf-8") as f:
            f.write("docs_src/site/secret.env\ndocs_src/site/private/\n")
        _git(pipeline, "add", "-A")
        _git(pipeline, "add", "-f", "docs_src/site/secret.env ", "docs_src/site/private\\key.env")
        _git(pipeline, "commit", "--quiet", "-m", "Decoys")
        paths, skipped = snapshot.document_paths(pipeline)
        assert "docs_src/site/secret.env" not in paths and "docs_src/site/private/key.env" not in paths
        assert ("docs_src/site/secret.env ", snapshot.NOT_A_PLAIN_PATH) in skipped
        snapshot.make(pipeline)
        for file in Path(str(default_store())).rglob("*"):
            if file.is_file():
                assert b"IGNORED SECRET" not in file.read_bytes(), file

    def test_git_is_asked_literally(self, pipeline):
        dataframes = {**MANIFEST["dataframes"], "other": {"path": "./_data/treasury.parquet", "docs_path": "docs_src/*"}}
        _set(pipeline, dataframes=dataframes)
        paths, _ = snapshot.document_paths(pipeline)
        assert "docs_src/method.md" not in paths  # a glob would have listed it

    def test_a_copy_reads_the_file_it_looked_at(self, pipeline, tmp_path, monkeypatch):
        outside = tmp_path / "outside.md"
        outside.write_text("OUTSIDE SECRET", encoding="utf-8")
        real_open = snapshot.os.open

        def swap_then_open(path, flags, *args, **kwargs):
            # Between looking and opening, the file becomes a link to somewhere else
            if str(path).endswith("docs_src/treasury.md") and not Path(path).is_symlink():
                Path(path).unlink()
                Path(path).symlink_to(outside)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(snapshot.os, "open", swap_then_open)
        taken = snapshot.make(pipeline).snapshot
        assert (pipeline / "docs_src" / "treasury.md").is_symlink()  # the swap happened
        assert "docs_src/treasury.md" not in taken.documents["files"]
        for file in Path(str(default_store())).rglob("*"):
            if file.is_file():
                assert b"OUTSIDE SECRET" not in file.read_bytes(), file

    def test_a_named_file_git_does_not_track_is_said(self, pipeline):
        (pipeline / "docs_src" / "untracked.md").write_text("draft", encoding="utf-8")
        with open(pipeline / ".gitignore", "a", encoding="utf-8") as f:
            f.write("docs_src/untracked.md\n")
        dataframes = {**MANIFEST["dataframes"], "treasury": {**MANIFEST["dataframes"]["treasury"], "docs_path": "./docs_src/untracked.md"}}
        _set(pipeline, dataframes=dataframes)
        _, skipped = snapshot.document_paths(pipeline)
        assert ("docs_src/untracked.md", snapshot.NOT_TRACKED) in skipped

    def test_nothing_is_written_when_an_object_is_missing(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        default_store().delete(taken.assets["treasury"]["content_hash"])
        with pytest.raises(snapshot.SnapshotError, match="does not have 1 object"):
            snapshot.materialize(taken, tmp_path / "laid")
        assert not (tmp_path / "laid").exists()

    def test_a_file_is_not_a_folder(self, pipeline, tmp_path):
        taken = snapshot.make(pipeline).snapshot
        (tmp_path / "afile").write_text("x", encoding="utf-8")
        with pytest.raises(snapshot.SnapshotError, match="is a file"):
            snapshot.materialize(taken, tmp_path / "afile")

    def test_no_documents_does_not_make_a_snapshot_every_run(self, pipeline):
        _git(pipeline, "rm", "--quiet", "--cached", "-r", ".")
        (pipeline / ".gitignore").write_text("*\n", encoding="utf-8")
        _git(pipeline, "add", "-f", ".gitignore")
        _git(pipeline, "commit", "--quiet", "-m", "Nothing tracked but the ignore file")
        first = snapshot.make(pipeline)
        assert first.made and first.snapshot.documents is None
        assert snapshot.make(pipeline).made is False

    def test_made_again_for_documents_keeps_the_run_note(self, pipeline):
        first = snapshot.make(pipeline, built_by_run=True).snapshot
        store = default_store()
        store.remove_snapshot(first.path)
        snapshot._write(dataclasses.replace(first, index=None, documents=None, path=None), store)
        again = snapshot.make(pipeline)  # a plain `chartbook snapshot`
        assert again.made and again.snapshot.built_by_run

    def test_looking_takes_no_git_lock(self, pipeline):
        import os

        index_file = pipeline / ".git" / "index"
        before = index_file.stat().st_mtime_ns
        os.utime(pipeline / "chartbook.toml")  # a stat change git status would refresh the index for
        snapshot.make(pipeline)
        assert index_file.stat().st_mtime_ns == before


class TestTheLaidOutVersion:
    def test_it_keeps_its_pipelines_id_whatever_the_folder_is_called(self, pipeline, tmp_path):
        manifest = dict(MANIFEST, project={"name": "Rates"})  # no id: it comes from the folder and git
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
        _git(pipeline, "commit", "--quiet", "-am", "No explicit id")
        taken = snapshot.make(pipeline).snapshot
        assert taken.pipeline == "rates"
        laid = snapshot.materialize(taken, tmp_path / "v-something-else")
        from chartbook.manifest import load_manifest

        assert load_manifest(laid.folder)["project"]["id"] == "rates"

    def test_scores_are_written_back_and_the_code_time_is_the_versions(self, pipeline, tmp_path, monkeypatch):
        models = {"ar1": {**MANIFEST["models"]["ar1"], "metrics_path": "./_output/ar1_metrics.json"}}
        (pipeline / "_output" / "ar1_metrics.json").write_text('{"rmse": 0.5}', encoding="utf-8")  # a build writes it; git ignores it
        _set(pipeline, models=models)
        taken = snapshot.make(pipeline).snapshot
        assert taken.assets["model/ar1"]["metrics"] == {"rmse": 0.5}
        laid = snapshot.materialize(taken, tmp_path / "v1")
        assert json.loads((laid.folder / "_output" / "ar1_metrics.json").read_text(encoding="utf-8")) == {"rmse": 0.5}
        marker = json.loads((laid.folder / ".chartbook-version.json").read_text(encoding="utf-8"))
        assert marker["pipeline"] == "acme/rates" and marker["commit"] == taken.commit and marker["code_changed_at"]
        from chartbook.manifest import find_latest_code_change

        from datetime import datetime, timezone

        recorded = datetime.strptime(marker["code_changed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert find_latest_code_change(laid.folder) == datetime.fromtimestamp(recorded.timestamp())
        monkeypatch.chdir(laid.folder)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"])
        assert result.exit_code == 0, result.output

    def test_a_named_site_dir_with_nothing_kept_is_made(self, pipeline, tmp_path, monkeypatch):
        (pipeline / "pages").mkdir()
        (pipeline / "pages" / "linked.md").symlink_to(tmp_path)
        _set(pipeline, project={**MANIFEST["project"], "site_dir": "./pages"})
        laid = snapshot.materialize(snapshot.make(pipeline).snapshot, tmp_path / "v1")
        assert (laid.folder / "pages").is_dir()
        monkeypatch.chdir(laid.folder)
        assert CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"]).exit_code == 0
