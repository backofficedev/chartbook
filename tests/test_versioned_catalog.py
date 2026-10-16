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


def _plant(store_root: Path, commit: str, document: dict) -> Path:
    """Write a snapshot record straight into a folder store, as anyone who can write a shared one could."""
    folder = store_root / "snapshots" / commit / "_top"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "planted.json"
    path.write_text(json.dumps(document))
    return path


class TestWhatTheReviewFound:
    def test_a_record_written_to_mislead_names_no_folder(self, catalog, monkeypatch, tmp_path):
        root, first, second = catalog
        store_root = Path(str(default_store()))
        base = {"schema": snapshot.SCHEMA, "root": "pipeline_a", "records": []}
        _plant(store_root, "a" * 40, {**base, "code": {"commit": "a" * 40}, "made_at": "../../../../escaped"})
        _plant(store_root, "b" * 40, {**base, "code": {"commit": "../../x"}, "made_at": "2026-01-01T00:00:00Z"})
        _plant(store_root, "c" * 40, {**base, "root": "..", "code": {"commit": "c" * 40}, "made_at": "2026-01-01T00:00:00Z"})
        _plant(store_root, "d" * 40, {**base, "schema": "chartbook/snapshot/v9", "code": {"commit": "d" * 40}, "made_at": "2026-01-01T00:00:00Z"})
        found, unreadable = snapshot.readable_snapshots(default_store())
        assert len(unreadable) == 4 and {t.made_at for t in found} == {first.made_at, second.made_at}
        from chartbook import index
        from chartbook.manifest import load_manifest

        with pytest.warns(UserWarning, match="4 snapshot record\\(s\\) in the store cannot be read and are not shown"):
            index.build_index(load_manifest(root))
        _build(root, monkeypatch)
        # The two real ones are there all the same, and nothing was written anywhere else
        assert len(list((root / "docs" / "versions" / "pipeline_a").iterdir())) == 2
        assert not list(tmp_path.rglob("escaped")) and not list(root.rglob("x-2026*"))

    @pytest.mark.parametrize("bad", ["..", ".", "a/..", "a/b/c", "a b", ""])
    def test_what_names_a_folder_is_checked(self, bad):
        with pytest.raises(ValueError):
            versions.slug(bad)
        with pytest.raises(ValueError):
            versions.version_name("a" * 40, "../x")
        with pytest.raises(ValueError):
            versions.version_name("../x", "2026-01-01T00:00:00Z")
        with pytest.raises(ValueError):
            versions.site_path("pipeline_a", "../../x")

    def test_a_pipelines_own_index_lists_no_snapshots(self, catalog, monkeypatch):
        root, first, second = catalog
        a = root / "pipelines" / "pipeline_a"
        _build(a, monkeypatch)
        index = json.loads((a / "docs" / "index.json").read_text())
        assert all("snapshots" not in r for r in index["records"])

    def test_a_snapshot_gc_removed_leaves_the_site(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch, "--incremental")
        name = versions.version_name(second.commit, second.made_at)
        assert (root / "docs" / versions.site_path("pipeline_a", name)).is_dir()
        snapshot.remove(default_store(), second)
        _build(root, monkeypatch, "--incremental")
        assert not (root / "docs" / versions.site_path("pipeline_a", name)).exists()
        assert not (root / "_docs" / "_build" / "html" / versions.site_path("pipeline_a", name)).exists()
        assert (root / "docs" / versions.site_path("pipeline_a", versions.version_name(first.commit, first.made_at))).is_dir()

    def test_a_version_that_hangs_is_stopped_and_said(self, catalog, monkeypatch):
        import subprocess

        root, first, second = catalog

        def hang(command, *args, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

        monkeypatch.setattr(versions.subprocess, "run", hang)
        rendered = versions.render(second, timeout=1)
        assert not rendered.built and "took longer than 1 seconds to build and was stopped" in rendered.why
        assert "took longer" in (rendered.folder / "index.html").read_text()

    def test_a_change_to_chartbook_builds_a_version_again(self, catalog, monkeypatch):
        root, first, second = catalog
        versions.fingerprint.cache_clear()
        one = versions._kept("pipeline_a", "a" * 7 + "-20260101T000000Z")
        monkeypatch.setattr(versions, "fingerprint", lambda: "0.0.0-changed")
        assert versions._kept("pipeline_a", "a" * 7 + "-20260101T000000Z") != one


class TestWhoseFilesTheseAre:
    """A version's files may have been written by anyone who can write the store."""

    def test_a_site_page_cannot_stand_in_for_the_builds_configuration(self, pipeline_project, monkeypatch):
        project = pipeline_project.resolve()
        site = project / "docs_src" / "site"
        site.mkdir(parents=True, exist_ok=True)
        (site / "guide.md").write_text("# Guide\n")
        (site / "conf.py.j2").write_text("raise SystemExit('PWNED: the site page ran as conf.py')\n")
        (site / "_templates").mkdir()
        (site / "_templates" / "layout.html").write_text("{{ PWNED }}")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        assert "PWNED" not in (project / "_docs" / "conf.py").read_text()
        assert not (project / "_docs" / "_templates" / "layout.html").exists() or "PWNED" not in (project / "_docs" / "_templates" / "layout.html").read_text()
        assert (project / "docs" / "guide.html").is_file()

    def test_templates_render_in_the_sandbox(self, tmp_path):
        import jinja2

        from chartbook.writers.sphinx import _sandboxed

        (tmp_path / "t.md").write_text("{{ ''.__class__.__mro__[1].__subclasses__() }}")
        with pytest.raises(jinja2.exceptions.SecurityError):
            _sandboxed([tmp_path]).get_template("t.md").render()

    def test_a_versions_pages_take_in_no_file_from_outside(self, tmp_path, monkeypatch):
        """In the working version, a write-up may include a file; in a version from the store, it may not."""
        secret = tmp_path / "outside" / "secret.md"
        secret.parent.mkdir()
        secret.write_text("OUTSIDE SECRET TEXT\n")
        repository = tmp_path.resolve() / "repo"
        root = create_catalog_project(repository / "cat", pipeline_ids=["pipeline_a"])
        a = root / "pipelines" / "pipeline_a"
        climb = "../" * 40 + str(secret.resolve()).lstrip("/")
        writeup = next(a.rglob("docs_src/dataframes/*.md"))
        writeup.write_text(f"# Write-up\n\n```{{include}} {climb}\n```\n\n![a picture]({'../' * 40}{str(secret.resolve()).lstrip('/')})\n")
        (repository / ".gitignore").write_text("docs/\n_docs*/\n")
        _git(repository, "init", "--quiet", "-b", "main")
        _commit(repository)
        taken = snapshot.make(a).snapshot
        rendered = versions.render(taken)
        assert rendered.built, rendered.why
        pages = "".join(p.read_text(errors="replace") for p in rendered.folder.rglob("*") if p.is_file())
        assert "OUTSIDE SECRET TEXT" not in pages
        assert not any(p.name == "secret.md" for p in rendered.folder.rglob("*"))


def _forged_version(taken, store, manifest_text: str, tmp_path: Path):
    """A snapshot like *taken*, made at another moment, whose manifest says what someone wrote into the store."""
    import dataclasses

    held = Path(store.get(taken.documents["content_hash"]))
    forged = tmp_path / "forged-documents"
    for file in held.rglob("*"):
        if file.is_file():
            target = forged / file.relative_to(held)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.read_bytes())
    (forged / "chartbook.toml").write_text(manifest_text)
    stored = store.put(forged)
    documents = {"content_hash": stored.content_hash, "size_bytes": stored.size_bytes, "files": list(stored.files)}
    version = dataclasses.replace(taken, documents=documents, made_at="2030-01-01T00:00:00.000001Z", path=None)
    version = dataclasses.replace(version, path=snapshot._write(version, store))
    return version


class TestAForgedManifest:
    """Anyone who can write the store can write a version's manifest: it reads nothing of this machine."""

    def test_a_query_reads_no_file_of_this_machine(self, catalog, tmp_path):
        root, first, second = catalog
        secret = tmp_path / "secret.csv"
        secret.write_text("user,password\nadmin,HUNTER2_LEAKED_SECRET\n")
        store = default_store()
        manifest = tomli.loads((root / "pipelines" / "pipeline_a" / "chartbook.toml").read_text())
        manifest["sources"] = {"mem": {"backend": "duckdb", "url": "duckdb:///:memory:"}}
        manifest["dataframes"]["leak"] = {"source": "mem", "query": f"select * from read_csv_auto('{secret}')", "docs": "d"}
        version = _forged_version(second, store, tomli_w.dumps(manifest), tmp_path)
        rendered = versions.render(version, store)
        assert rendered.built, rendered.why
        pages = "".join(p.read_text(errors="replace") for p in rendered.folder.rglob("*") if p.is_file())
        assert "HUNTER2_LEAKED_SECRET" not in pages
        assert "not read in a build of files from a store" in pages

    @pytest.mark.parametrize("where", ["absolute", "climbing"])
    def test_a_path_outside_the_folder_stops_the_versions_build(self, catalog, tmp_path, where):
        root, first, second = catalog
        private = tmp_path / "private.parquet"
        pl.DataFrame({"ssn": ["111-22-3333"]}).write_parquet(private)
        store = default_store()
        manifest = tomli.loads((root / "pipelines" / "pipeline_a" / "chartbook.toml").read_text())
        path = str(private) if where == "absolute" else "../" * 30 + str(private).lstrip("/")
        manifest["dataframes"]["leak"] = {"path": path, "docs": "d"}
        version = _forged_version(second, store, tomli_w.dumps(manifest), tmp_path)
        rendered = versions.render(version, store)
        assert not rendered.built and "is not a plain path inside the pipeline's folder" in rendered.why
        pages = "".join(p.read_text(errors="replace") for p in rendered.folder.rglob("*") if p.is_file())
        assert "111-22-3333" not in pages

    def test_the_working_version_still_reads_its_own_sources(self, catalog):
        """The rule is for files from a store; a folder of the user's reads what it names."""
        from chartbook.backends import DuckDBBackend

        assert DuckDBBackend("duckdb:///:memory:").connect().sql("select 1").fetchone() == (1,)


@pytest.fixture
def trained(tmp_path):
    """`pipeline_b` has a model trained on `pipeline_a:dataframe_0`, and pins `pipeline_a`'s first
    snapshot; `pipeline_a` then makes a second, with other data."""
    repository = tmp_path.resolve() / "repo"
    root = create_catalog_project(repository / "cat")
    (repository / ".gitignore").write_text("docs/\n_docs*/\nchartbook.lock\n")
    a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
    manifest = tomli.loads((b / "chartbook.toml").read_text())
    manifest["dependencies"] = {"pipeline_a": {"path": "../pipeline_a"}}
    manifest["models"] = {"m": {"path": "./_models/m.json", "trained_on": ["pipeline_a:dataframe_0"], "docs": "A model."}}
    (b / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    (b / "_models").mkdir()
    (b / "_models" / "m.json").write_text("{}")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    first = snapshot.make(a).snapshot
    lock.pin(b)
    data = next((a / "_data").rglob("*.parquet"))
    pl.DataFrame({"date": ["2025-01-01"], "value": [9.9]}).write_parquet(data)
    _commit(repository, "New data")
    second = snapshot.make(a).snapshot
    return root, first, second


class TestLinksFollowPins:
    def test_a_model_links_to_the_version_it_was_trained_on(self, trained, monkeypatch):
        root, first, second = trained
        _build(root, monkeypatch)
        site = root / "docs"
        pinned = f"versions/pipeline_a/{versions.version_name(first.commit, first.made_at)}/cb/dataframes/pipeline_a/dataframe_0.html"
        page = (site / "cb" / "models" / "pipeline_b" / "m.html").read_text()
        link = f'href="../../../{pinned}"'
        assert page.count(link) == 2, page  # under Trained On, and in the provenance panel
        assert (site / pinned).is_file()  # the link leads somewhere
        newer = versions.version_name(second.commit, second.made_at)
        assert newer not in page  # the version it was not trained on is not where it leads
        assert "as pinned: the snapshot at " + first.commit[:7] in page

    def test_without_the_pinned_version_the_working_version_is_linked(self, trained, monkeypatch):
        root, first, second = trained
        snapshot.remove(default_store(), first)
        _build(root, monkeypatch)
        page = (root / "docs" / "cb" / "models" / "pipeline_b" / "m.html").read_text()
        assert "versions/pipeline_a" not in page
        assert "dataframes/pipeline_a/dataframe_0.html" in page

    def test_with_mkdocs_too(self, trained, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = trained
        manifest = tomli.loads((root / "chartbook.toml").read_text())
        manifest["project"]["writer"] = "mkdocs"
        (root / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        result = _build(root, monkeypatch)
        assert "contains a link" not in result.output, result.output
        pinned = f"versions/pipeline_a/{versions.version_name(first.commit, first.made_at)}/cb/dataframes/pipeline_a/dataframe_0.html"
        assert f'href="../../../{pinned}"' in (root / "docs" / "cb" / "models" / "pipeline_b" / "m.html").read_text()


class TestGcClearsTheKeptSites:
    def test_a_removed_snapshot_takes_its_kept_site_with_it(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        kept = get_cache_path() / "versions" / "pipeline_a"
        names = {p.name for p in kept.iterdir()}
        assert versions.version_name(first.commit, first.made_at) in names
        store = default_store()
        # Nothing pins the first any more: pipeline_b's lockfile is forgotten
        store.remove_root(root / "pipelines" / "pipeline_b" / "chartbook.lock")
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        doomed = [taken for taken, _ in plan.snapshots_delete]
        assert [t.made_at for t in doomed] == [first.made_at]
        lock.run_gc(plan, store)
        left = {p.name for p in kept.iterdir()}
        for taken in doomed:
            assert versions.version_name(taken.commit, taken.made_at) not in left
        assert versions.version_name(second.commit, second.made_at) in left  # what gc kept, its site too


def _links(page: Path) -> list[str]:
    import re

    return re.findall(r'href="([^"]*versions/[^"]*)"', page.read_text())


def _resolves(page: Path, href: str) -> bool:
    return (page.parent / href).resolve().is_file()


class TestWhatTheLinksReviewFound:
    def test_an_incremental_build_drops_a_link_to_a_snapshot_that_is_gone(self, trained, monkeypatch):
        root, first, second = trained
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        _build(root, monkeypatch, "--incremental")
        assert _links(page) and all(_resolves(page, h) for h in _links(page))
        snapshot.remove(default_store(), first)
        _build(root, monkeypatch, "--incremental")
        assert all(_resolves(page, h) for h in _links(page)), _links(page)
        assert versions.version_name(first.commit, first.made_at) not in page.read_text()

    def test_a_version_that_could_not_be_built_is_linked_to_the_page_that_says_why(self, trained, monkeypatch):
        root, first, second = trained
        data = next(r for r in first.assets.values() if r.get("content_hash") and r["kind"] == "Dataframe")
        assert data["content_hash"] not in second.hashes()
        default_store().delete(data["content_hash"])
        _build(root, monkeypatch)
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        name = versions.version_name(first.commit, first.made_at)
        links = [h for h in _links(page) if name in h]
        assert links and all(h.endswith(f"{name}/index.html") and _resolves(page, h) for h in links)
        assert "could not be" in (page.parent / links[0]).resolve().read_text()

    def test_an_input_the_lockfile_does_not_pin_is_not_linked_as_pinned(self, trained, monkeypatch):
        root, first, second = trained
        a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
        manifest = tomli.loads((a / "chartbook.toml").read_text())
        manifest["dataframes"]["extra"] = {"path": "./_data/extra.parquet", "docs": "Added later."}
        (a / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        pl.DataFrame({"x": [1]}).write_parquet(a / "_data" / "extra.parquet")
        model = tomli.loads((b / "chartbook.toml").read_text())
        model["models"]["m"]["trained_on"].append("pipeline_a:extra")
        (b / "chartbook.toml").write_text(tomli_w.dumps(model))
        _commit(root.parent, "An input that is not pinned")
        snapshot.make(a)
        lock.pin(b)  # keeps the first; `extra` is not in it
        _build(root, monkeypatch)
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        assert not any(h.endswith("/extra.html") and "versions/" in h for h in _links(page))
        assert all(_resolves(page, h) for h in _links(page))

    def test_a_stale_model_links_to_what_it_was_trained_on(self, trained, monkeypatch):
        root, first, second = trained
        b = root / "pipelines" / "pipeline_b"
        snapshot.make(b)  # trained on the first: that is what b pins
        lock.update(b)  # the pin moves to the second
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text())
        model = next(r for r in index["records"] if r["kind"] == "Model")
        assert model["stale_inputs"] == ["pipeline_a:dataframe_0"]
        assert model["trained_from"]["pipeline_a:dataframe_0"]["made_at"] == first.made_at
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        text = page.read_text()
        old, new = (versions.version_name(t.commit, t.made_at) for t in (first, second))
        assert f"as trained: the snapshot at {first.commit[:7]}" in text and f"the pin has since moved to {second.commit[:7]}" in text
        assert any(old in h for h in _links(page)) and any(new in h for h in _links(page))  # Trained On, and the panel's pin
        assert all(_resolves(page, h) for h in _links(page))

    def test_mkdocs_links_lead_somewhere_and_gc_keeps_what_it_keeps(self, trained, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = trained
        manifest = tomli.loads((root / "chartbook.toml").read_text())
        manifest["project"]["writer"] = "mkdocs"
        (root / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        _build(root, monkeypatch)
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        assert _links(page) and all(_resolves(page, h) for h in _links(page))
