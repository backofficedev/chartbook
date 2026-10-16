"""A catalog shows every snapshot of every pipeline, each its own site built from the store alone
(docs_src/design/versioned-catalog.md, step 2)."""

import json
from pathlib import Path

import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import lock, snapshot, versions
from chartbook.cli import main
from chartbook.config import get_cache_path
from chartbook.store import default_store
from tests.fixtures import create_catalog_project
from tests.test_model_versions import _git


def _commit(repository: Path, message: str = "Work") -> None:
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", message)


@pytest.fixture
def catalog(tmp_path):
    """A catalog of `pipeline_a` and `pipeline_b` in one repository; `pipeline_b` depends on
    `pipeline_a`. `pipeline_a` has two snapshots, and `pipeline_b` pins the first."""
    repository = tmp_path.resolve() / "repo"
    root = create_catalog_project(repository / "cat")
    (repository / ".gitignore").write_text("docs/\n_docs*/\nchartbook.lock\n")
    a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
    manifest = tomli.loads((b / "chartbook.toml").read_text())
    manifest["dependencies"] = {"pipeline_a": {"path": "../pipeline_a"}}
    (b / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    first = snapshot.make(a).snapshot
    lock.pin(b)  # pins the first
    data = next((a / "_data").rglob("*.parquet"))
    pl.DataFrame({"date": ["2025-01-01"], "value": [9.9]}).write_parquet(data)
    _commit(repository, "New data")
    second = snapshot.make(a).snapshot
    return root, first, second


def _build(root: Path, monkeypatch, *arguments):
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ["docs", "./docs", "-f", *arguments])
    assert result.exit_code == 0, result.output
    return result


class TestTheIndex:
    def test_a_pipeline_lists_its_snapshots_newest_first(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text())
        records = {r["id"]: r for r in index["records"] if r["kind"] == "Pipeline"}
        listed = records["pipeline_a"]["snapshots"]
        assert [(s["commit"], s["made_at"]) for s in listed] == [(second.commit, second.made_at), (first.commit, first.made_at)]
        assert listed[0]["name"] == versions.version_name(second.commit, second.made_at)
        assert "snapshots" not in records["pipeline_b"]


class TestTheSite:
    def test_every_snapshot_is_its_own_site_and_the_versions_page_lists_them(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        site = root / "docs"
        for taken in (first, second):
            front = site / versions.site_path("pipeline_a", versions.version_name(taken.commit, taken.made_at)) / "index.html"
            text = front.read_text()
            assert "A snapshot of this pipeline:" in text and taken.commit[:7] in text
        page = (site / "cb" / "versions.html").read_text()
        assert page.count('href="../versions/pipeline_a/') == 2
        assert "pinned by <code>pipeline_b</code>" in page  # the first, as pipeline_b's lockfile says
        assert page.index(second.commit[:7]) < page.index(first.commit[:7])  # newest first
        assert "No snapshot of it is in the store." in page  # pipeline_b
        assert "cb/versions.html" in (site / "index.html").read_text()
        # The catalog's search finds the working versions; each version's site is its own
        assert not (site / "versions" / "pipeline_a" / "searchindex.js").exists()

    def test_a_version_is_built_once_on_this_machine(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        kept = get_cache_path() / "versions" / "pipeline_a"
        stamps = {p: p.stat().st_mtime_ns for p in kept.rglob(".chartbook-version-site")}
        assert len(stamps) == 2
        calls = []
        real = versions.subprocess.run

        def counted(command, *args, **kwargs):
            if "chartbook.cli" in command:  # a version's own build; git and the rest pass through
                calls.append(command)
            return real(command, *args, **kwargs)

        monkeypatch.setattr(versions.subprocess, "run", counted)
        _build(root, monkeypatch)
        assert calls == [] and {p: p.stat().st_mtime_ns for p in kept.rglob(".chartbook-version-site")} == stamps
        assert (root / "docs" / "versions" / "pipeline_a").is_dir()

    def test_an_incremental_catalog_build_keeps_the_versions(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch, "--incremental")
        _build(root, monkeypatch, "--incremental")
        name = versions.version_name(second.commit, second.made_at)
        assert (root / "docs" / versions.site_path("pipeline_a", name) / "index.html").is_file()
        assert (root / "docs" / "cb" / "versions.html").is_file()

    def test_a_version_that_cannot_be_built_says_why(self, catalog, monkeypatch):
        root, first, second = catalog
        store = default_store()
        data = next(r for r in first.assets.values() if r.get("content_hash") and r["kind"] == "Dataframe")
        if data["content_hash"] not in second.hashes():
            store.delete(data["content_hash"])
        else:  # the same bytes in both: take the documents instead
            store.delete(first.documents["content_hash"])
        result = _build(root, monkeypatch)
        assert f"warning: pipeline_a at {first.commit[:7]}: it could not be laid out from the store" in result.output
        name = versions.version_name(first.commit, first.made_at)
        placeholder = (root / "docs" / versions.site_path("pipeline_a", name) / "index.html").read_text()
        assert "its site could not be built" in placeholder or "could not be laid out" in placeholder
        # The other version is unharmed
        other = versions.version_name(second.commit, second.made_at)
        assert "A snapshot of this pipeline:" in (root / "docs" / versions.site_path("pipeline_a", other) / "index.html").read_text()

    def test_a_pipeline_site_shows_no_versions_page(self, catalog, monkeypatch):
        root, first, second = catalog
        a = root / "pipelines" / "pipeline_a"
        _build(a, monkeypatch)
        assert not (a / "docs" / "cb" / "versions.html").exists() and not (a / "docs" / "versions").exists()


class TestWithMkDocs:
    def test_the_versions_page_and_the_versions(self, catalog, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = catalog
        manifest = tomli.loads((root / "chartbook.toml").read_text())
        manifest["project"]["writer"] = "mkdocs"
        (root / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        result = _build(root, monkeypatch)
        assert "contains a link" not in result.output, result.output
        page = (root / "docs" / "cb" / "versions.html").read_text()
        assert page.count('href="../versions/pipeline_a/') == 2
        name = versions.version_name(second.commit, second.made_at)
        assert (root / "docs" / versions.site_path("pipeline_a", name) / "index.html").is_file()
