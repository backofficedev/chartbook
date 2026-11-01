"""A catalog shows every snapshot of every pipeline, each its own site built from the store alone
(docs_src/design/versioned-catalog.md, step 2)."""

import html
import json
import re
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
from tests.fixtures import remove_tree


def _commit(repository: Path, message: str = "Work") -> None:
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", message)


@pytest.fixture
def catalog(tmp_path):
    """A catalog of `pipeline_a` and `pipeline_b` in one repository; `pipeline_b` depends on
    `pipeline_a`. `pipeline_a` has two snapshots, and `pipeline_b` pins the first."""
    repository = tmp_path.resolve() / "repo"
    root = create_catalog_project(repository / "cat")
    (repository / ".gitignore").write_text("docs/\n_docs*/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
    manifest = tomli.loads((b / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["dependencies"] = {"pipeline_a": {"path": "../pipeline_a"}}
    (b / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    first = snapshot.make(a).snapshot
    lock.pin(b)  # pins the first
    data = next((a / "_data").rglob("*.parquet"))
    pl.DataFrame({"date": ["2025-01-01"], "value": [9.9]}).write_parquet(data)
    _commit(repository, "New data")
    second = snapshot.make(a).snapshot
    from tests.fixtures import publish_catalog
    publish_catalog(root)
    return root, first, second


def _build(root: Path, monkeypatch, *arguments):
    if not (root / "catalog.toml").is_file() and (root / "chartbook.toml").is_file():
        raw = tomli.loads((root / "chartbook.toml").read_text(encoding="utf-8"))
        if raw.get("project", {}).get("type") == "catalog" or "pipelines" in raw:
            from tests.fixtures import publish_catalog
            publish_catalog(root)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", *arguments])
    assert result.exit_code == 0, result.output
    return result


class TestTheIndex:
    def test_a_pipeline_lists_its_snapshots_newest_first(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
        records = {r["id"]: r for r in index["records"] if r["kind"] == "Pipeline"}
        listed = records["pipeline_a"]["snapshots"]
        assert [(s["commit"], s["made_at"]) for s in listed] == [(second.commit, second.made_at), (first.commit, first.made_at)]
        assert listed[0]["name"] == versions.version_name(second.commit, second.made_at)
        assert records["pipeline_b"]["snapshots"]


class TestTheSite:
    def test_every_snapshot_is_its_own_site_and_the_versions_page_lists_them(self, catalog, monkeypatch):
        root, first, second = catalog
        _build(root, monkeypatch)
        site = root / "docs"
        for taken in (first, second):
            front = site / versions.site_path("pipeline_a", versions.version_name(taken.commit, taken.made_at)) / "index.html"
            text = front.read_text(encoding="utf-8")
            assert "A snapshot of this pipeline:" in text and taken.commit[:7] in text
        page = (site / "cb" / "versions.html").read_text(encoding="utf-8")
        assert page.count('href="../versions/pipeline_a/') == 2
        assert "pinned by <code>pipeline_b</code>" in page  # the first, as pipeline_b's lockfile says
        assert page.index(second.commit[:7]) < page.index(first.commit[:7])  # newest first
        assert "pipeline_b" in page  # pipeline_b
        assert "cb/versions.html" in (site / "index.html").read_text(encoding="utf-8")
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
        assert f"warning: pipeline_a at {first.commit[:7]}: it is not all in the store yet" in result.output
        name = versions.version_name(first.commit, first.made_at)
        placeholder = (root / "docs" / versions.site_path("pipeline_a", name) / "index.html").read_text(encoding="utf-8")
        assert "not all in the store yet" in placeholder
        # The other version is unharmed
        other = versions.version_name(second.commit, second.made_at)
        assert "A snapshot of this pipeline:" in (root / "docs" / versions.site_path("pipeline_a", other) / "index.html").read_text(encoding="utf-8")

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
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest["project"]["writer"] = "mkdocs"
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        result = _build(root, monkeypatch)
        assert "contains a link" not in result.output, result.output
        page = (root / "docs" / "cb" / "versions.html").read_text(encoding="utf-8")
        assert page.count('href="../versions/pipeline_a/') == 2
        name = versions.version_name(second.commit, second.made_at)
        assert (root / "docs" / versions.site_path("pipeline_a", name) / "index.html").is_file()


def _plant(store_root: Path, commit: str, document: dict) -> Path:
    """Write a snapshot record straight into a folder store, as anyone who can write a shared one could."""
    named = commit[:12] if len(commit) == 40 and all(c in "0123456789abcdef" for c in commit) else "0" * 12
    folder = store_root / "pipelines" / "pipeline_a" / f"2026-01-01T000000Z_{named}" / "_chartbook"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "snapshot.json"  # named as a record is, or it is passed over
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
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
        assert len(unreadable) == 4 and {t.made_at for t in found if t.pipeline == "pipeline_a"} == {first.made_at, second.made_at}
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
        index = json.loads((a / "docs" / "index.json").read_text(encoding="utf-8"))
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
        assert "took longer" in (rendered.folder / "index.html").read_text(encoding="utf-8")

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
        (site / "guide.md").write_text("# Guide\n", encoding="utf-8", newline="\n")
        (site / "conf.py.j2").write_text("raise SystemExit('PWNED: the site page ran as conf.py')\n", encoding="utf-8", newline="\n")
        (site / "_templates").mkdir()
        (site / "_templates" / "layout.html").write_text("{{ PWNED }}", encoding="utf-8", newline="\n")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        assert "PWNED" not in (project / "_docs" / "conf.py").read_text(encoding="utf-8")
        assert not (project / "_docs" / "_templates" / "layout.html").exists() or "PWNED" not in (project / "_docs" / "_templates" / "layout.html").read_text(encoding="utf-8")
        assert (project / "docs" / "guide.html").is_file()

    def test_templates_render_in_the_sandbox(self, tmp_path):
        import jinja2

        from chartbook.writers.sphinx import _sandboxed

        (tmp_path / "t.md").write_text("{{ ''.__class__.__mro__[1].__subclasses__() }}", encoding="utf-8", newline="\n")
        with pytest.raises(jinja2.exceptions.SecurityError):
            _sandboxed([tmp_path]).get_template("t.md").render()

    def test_a_versions_pages_take_in_no_file_from_outside(self, tmp_path, monkeypatch):
        """In the working version, a write-up may include a file; in a version from the store, it may not."""
        secret = tmp_path / "outside" / "secret.md"
        secret.parent.mkdir()
        secret.write_text("OUTSIDE SECRET TEXT\n", encoding="utf-8", newline="\n")
        repository = tmp_path.resolve() / "repo"
        root = create_catalog_project(repository / "cat", pipeline_ids=["pipeline_a"])
        a = root / "pipelines" / "pipeline_a"
        climb = "../" * 40 + str(secret.resolve()).lstrip("/")
        writeup = next(a.rglob("docs_src/dataframes/*.md"))
        writeup.write_text(f"# Write-up\n\n```{{include}} {climb}\n```\n\n![a picture]({'../' * 40}{str(secret.resolve()).lstrip('/')})\n", encoding="utf-8", newline="\n")
        (repository / ".gitignore").write_text("docs/\n_docs*/\n", encoding="utf-8", newline="\n")
        _git(repository, "init", "--quiet", "-b", "main")
        _commit(repository)
        taken = snapshot.make(a).snapshot
        rendered = versions.render(taken)
        assert rendered.built, rendered.why
        pages = "".join(p.read_text(errors="replace", encoding="utf-8") for p in rendered.folder.rglob("*") if p.is_file())
        assert "OUTSIDE SECRET TEXT" not in pages
        assert not any(p.name == "secret.md" for p in rendered.folder.rglob("*"))


def _forged_version(taken, store, manifest_text: str, tmp_path: Path):
    """A snapshot like *taken*, made at another moment, whose manifest says what someone wrote into the store."""
    import dataclasses

    forged = tmp_path / "forged-documents"
    for relative, file in store.files(taken.documents["content_hash"]).by_relative().items():
        if file.is_file():
            target = forged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.read_bytes())
    (forged / "chartbook.toml").write_text(manifest_text, encoding="utf-8", newline="\n")
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
        secret.write_text("user,password\nadmin,HUNTER2_LEAKED_SECRET\n", encoding="utf-8", newline="\n")
        store = default_store()
        manifest = tomli.loads((root / "pipelines" / "pipeline_a" / "chartbook.toml").read_text(encoding="utf-8"))
        manifest["sources"] = {"mem": {"backend": "duckdb", "url": "duckdb:///:memory:"}}
        manifest["dataframes"]["leak"] = {"source": "mem", "query": f"select * from read_csv_auto('{secret}')", "docs": "d"}
        version = _forged_version(second, store, tomli_w.dumps(manifest), tmp_path)
        rendered = versions.render(version, store)
        assert rendered.built, rendered.why
        pages = "".join(p.read_text(errors="replace", encoding="utf-8") for p in rendered.folder.rglob("*") if p.is_file())
        assert "HUNTER2_LEAKED_SECRET" not in pages
        assert "not read in a build of files from a store" in pages

    @pytest.mark.parametrize("where", ["absolute", "climbing"])
    def test_a_path_outside_the_folder_stops_the_versions_build(self, catalog, tmp_path, where):
        root, first, second = catalog
        private = tmp_path / "private.parquet"
        pl.DataFrame({"ssn": ["111-22-3333"]}).write_parquet(private)
        store = default_store()
        manifest = tomli.loads((root / "pipelines" / "pipeline_a" / "chartbook.toml").read_text(encoding="utf-8"))
        path = str(private) if where == "absolute" else "../" * 30 + str(private).lstrip("/")
        manifest["dataframes"]["leak"] = {"path": path, "docs": "d"}
        version = _forged_version(second, store, tomli_w.dumps(manifest), tmp_path)
        rendered = versions.render(version, store)
        assert not rendered.built and "is not a plain path inside the pipeline's folder" in rendered.why
        pages = "".join(p.read_text(errors="replace", encoding="utf-8") for p in rendered.folder.rglob("*") if p.is_file())
        assert "111-22-3333" not in pages

    def test_the_working_version_still_reads_its_own_sources(self, catalog):
        """The rule is for files from a store; a folder of the user's reads what it names."""
        from chartbook.backends import DuckDBBackend

        assert DuckDBBackend("duckdb:///:memory:").connect().sql("select 1").fetchall() == [(1,)]


@pytest.fixture
def trained(tmp_path):
    """`pipeline_b` has a model trained on `pipeline_a:dataframe_0`, and pins `pipeline_a`'s first
    snapshot; `pipeline_a` then makes a second, with other data."""
    repository = tmp_path.resolve() / "repo"
    root = create_catalog_project(repository / "cat")
    (repository / ".gitignore").write_text("docs/\n_docs*/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
    manifest = tomli.loads((b / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["dependencies"] = {"pipeline_a": {"path": "../pipeline_a"}}
    manifest["models"] = {"m": {"path": "./_models/m.json", "trained_on": ["pipeline_a:dataframe_0"], "docs": "A model."}}
    (b / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
    (b / "_models").mkdir()
    (b / "_models" / "m.json").write_text("{}", encoding="utf-8", newline="\n")
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
        page = (site / "cb" / "models" / "pipeline_b" / "m.html").read_text(encoding="utf-8")
        link = f'href="../../../{pinned}"'
        assert page.count(link) == 2, page  # under Trained On, and in the provenance panel
        assert (site / pinned).is_file()  # the link leads somewhere
        newer = versions.version_name(second.commit, second.made_at)
        assert newer not in page  # the version it was not trained on is not where it leads
        assert "as pinned: the snapshot at " + first.commit[:7] in page

    def test_without_the_pinned_version_the_working_version_is_linked(self, trained, monkeypatch):
        root, first, second = trained
        from tests.fixtures import publish_catalog
        publish_catalog(root)
        snapshot.remove(default_store(), first)
        _build(root, monkeypatch)
        page = (root / "docs" / "cb" / "models" / "pipeline_b" / "m.html").read_text(encoding="utf-8")
        assert "versions/pipeline_a" not in page
        assert "dataframes/pipeline_a/dataframe_0.html" in page

    def test_with_mkdocs_too(self, trained, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = trained
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest["project"]["writer"] = "mkdocs"
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        result = _build(root, monkeypatch)
        assert "contains a link" not in result.output, result.output
        pinned = f"versions/pipeline_a/{versions.version_name(first.commit, first.made_at)}/cb/dataframes/pipeline_a/dataframe_0.html"
        assert f'href="../../../{pinned}"' in (root / "docs" / "cb" / "models" / "pipeline_b" / "m.html").read_text(encoding="utf-8")


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

    return re.findall(r'href="([^"]*versions/[^"]*)"', page.read_text(encoding="utf-8"))


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
        assert versions.version_name(first.commit, first.made_at) not in page.read_text(encoding="utf-8")

    def test_a_version_that_could_not_be_built_is_linked_to_the_page_that_says_why(self, trained, monkeypatch):
        root, first, second = trained
        from tests.fixtures import publish_catalog
        publish_catalog(root)
        data = next(r for r in first.assets.values() if r.get("content_hash") and r["kind"] == "Dataframe")
        assert data["content_hash"] not in second.hashes()
        default_store().delete(data["content_hash"])
        _build(root, monkeypatch)
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        name = versions.version_name(first.commit, first.made_at)
        links = [h for h in _links(page) if name in h]
        assert links and all(h.endswith(f"{name}/index.html") and _resolves(page, h) for h in links)
        assert "could not be" in (page.parent / links[0]).resolve().read_text(encoding="utf-8")

    def test_an_input_the_lockfile_does_not_pin_is_not_linked_as_pinned(self, trained, monkeypatch):
        root, first, second = trained
        a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
        manifest = tomli.loads((a / "chartbook.toml").read_text(encoding="utf-8"))
        manifest["dataframes"]["extra"] = {"path": "./_data/extra.parquet", "docs": "Added later."}
        (a / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        pl.DataFrame({"x": [1]}).write_parquet(a / "_data" / "extra.parquet")
        model = tomli.loads((b / "chartbook.toml").read_text(encoding="utf-8"))
        model["models"]["m"]["trained_on"].append("pipeline_a:extra")
        (b / "chartbook.toml").write_text(tomli_w.dumps(model), encoding="utf-8", newline="\n")
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
        snapshot.make(b)
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
        model = next(r for r in index["records"] if r["kind"] == "Model")
        assert model["stale_inputs"] == ["pipeline_a:dataframe_0"]
        assert model["trained_from"]["pipeline_a:dataframe_0"]["made_at"] == first.made_at
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        text = page.read_text(encoding="utf-8")
        old, new = (versions.version_name(t.commit, t.made_at) for t in (first, second))
        assert f"as trained: the snapshot at {first.commit[:7]}" in text and f"the pin has since moved to {second.commit[:7]}" in text
        assert any(old in h for h in _links(page)) and any(new in h for h in _links(page))  # Trained On, and the panel's pin
        assert all(_resolves(page, h) for h in _links(page))

    def test_mkdocs_links_lead_somewhere(self, trained, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = trained
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest["project"]["writer"] = "mkdocs"
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        _build(root, monkeypatch)
        page = root / "docs" / "cb" / "models" / "pipeline_b" / "m.html"
        assert _links(page) and all(_resolves(page, h) for h in _links(page))



def _trained_catalog(tmp_path, key: str = "pipeline_a"):
    """A catalog where pipeline_b's model is trained on pipeline_a:dataframe_0, known by *key*; nothing snapshotted yet."""
    repository = tmp_path.resolve() / "repo"
    root = create_catalog_project(repository / "cat")
    (repository / ".gitignore").write_text("docs/\n_docs*/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    a, b = root / "pipelines" / "pipeline_a", root / "pipelines" / "pipeline_b"
    manifest = tomli.loads((b / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["dependencies"] = {key: {"path": "../pipeline_a"}}
    manifest["models"] = {"m": {"path": "./_models/m.json", "trained_on": [f"{key}:dataframe_0"], "docs": "A model."}}
    (b / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
    (b / "_models").mkdir()
    (b / "_models" / "m.json").write_text("{}", encoding="utf-8", newline="\n")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    return repository, root, a, b


def _new_data(repository: Path, a: Path, value: float) -> None:
    data = next((a / "_data").rglob("*.parquet"))
    pl.DataFrame({"date": ["2025-01-01"], "value": [value]}).write_parquet(data)
    _commit(repository, f"Data {value}")


class TestWhatTheSecondLinksReviewFound:
    def test_a_dependency_known_by_another_name_still_links_to_what_it_was_trained_on(self, tmp_path, monkeypatch):
        repository, root, a, b = _trained_catalog(tmp_path, key="upstream")
        first = snapshot.make(a).snapshot
        lock.pin(b)
        snapshot.make(b)  # trained on the first
        _new_data(repository, a, 9.9)
        second = snapshot.make(a).snapshot
        lock.update(b)
        snapshot.make(b)
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
        model = next(r for r in index["records"] if r["kind"] == "Model")
        assert model["trained_from"] == {"pipeline_a:dataframe_0": {"commit": first.commit, "made_at": first.made_at}}
        pipeline_b = next(r for r in index["records"] if r["id"] == "pipeline_b")
        assert pipeline_b["dependencies"][0]["key"] == "upstream"
        text = (root / "docs" / "cb" / "models" / "pipeline_b" / "m.html").read_text(encoding="utf-8")
        assert f"as trained: the snapshot at {first.commit[:7]}" in text and f"moved to {second.commit[:7]}" in text

    def test_a_later_snapshot_of_the_same_bytes_is_not_what_it_was_trained_on(self, tmp_path, monkeypatch):
        repository, root, a, b = _trained_catalog(tmp_path)
        first = snapshot.make(a).snapshot
        lock.pin(b)
        snapshot.make(b)  # trained on the first
        (a / "README.md").write_text("# A\n\nA new README, the same data.\n", encoding="utf-8", newline="\n")
        _commit(repository, "README only")
        same_bytes = snapshot.make(a).snapshot
        assert same_bytes.made_at > first.made_at
        _new_data(repository, a, 7.7)
        snapshot.make(a)
        lock.update(b)
        snapshot.make(b)
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
        model = next(r for r in index["records"] if r["kind"] == "Model")
        assert model["trained_from"]["pipeline_a:dataframe_0"]["made_at"] == first.made_at

    def test_a_snapshot_that_leaves_the_store_mid_build_is_not_linked(self, trained, monkeypatch):
        root, first, second = trained
        _build(root, monkeypatch)
        index = json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))
        snapshot.remove(default_store(), first)  # as a gc elsewhere might, after the index was made
        done = versions.render_listed(index)
        pipeline_a = next(r for r in index["records"] if r["id"] == "pipeline_a")
        assert [e["made_at"] for e in pipeline_a["snapshots"]] == [second.made_at]
        assert ("pipeline_a", first.commit, first.made_at) not in done

    def test_the_diff_words_the_computed_fields(self):
        from chartbook import indexdiff

        base = {"schema": "chartbook/index/v1", "root": "c", "records": []}
        model = {"kind": "Model", "version": "chartbook/v1", "id": "b:model/m", "pipeline": "b"}
        pipeline = {"kind": "Pipeline", "version": "chartbook/v1", "id": "a", "snapshots": [{"commit": "a" * 40, "made_at": "2026-01-01T00:00:00Z", "rendered": True}]}
        before = {**base, "records": [{**model, "trained_from": {"a:d": {"commit": "a" * 40}}}, pipeline]}
        after = {**base, "records": [
            {**model, "trained_from": {"a:d": {"commit": "b" * 40}}},
            {**pipeline, "snapshots": [{**pipeline["snapshots"][0], "rendered": False}]},
        ]}
        text = indexdiff.format_diff(indexdiff.diff(before, after))
        assert "trained from another snapshot" in text and "declared differently" not in text
        assert "versions' sites built differently" in text


class TestAPipelineFromTheStoreAlone:
    """A catalog entry with no path: the pipeline's folder is not here, its snapshots are."""

    def _elsewhere(self, tmp_path) -> "snapshot.Snapshot":
        """A pipeline built and snapshotted somewhere else, then its folder gone from this machine."""
        import shutil

        from tests.fixtures import create_pipeline_project

        repository = tmp_path.resolve() / "elsewhere"
        project = create_pipeline_project(repository / "pipeline_c", pipeline_id="pipeline_c", pipeline_name="Pipeline C")
        manifest = tomli.loads((project / "chartbook.toml").read_text(encoding="utf-8"))
        manifest["project"]["description"] = "Made on another machine."
        (project / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        _git(repository, "init", "--quiet", "-b", "main")
        _commit(repository)
        taken = snapshot.make(project).snapshot
        remove_tree(repository)
        return taken

    def test_it_is_shown_from_its_snapshots(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        taken = self._elsewhere(tmp_path)
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest.setdefault("pipelines", {})["pipeline_c"] = {}
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        _build(root, monkeypatch)
        site = root / "docs"
        index = json.loads((site / "index.json").read_text(encoding="utf-8"))
        record = next(r for r in index["records"] if r["id"] == "pipeline_c")
        assert record["location"] == {"kind": "store"}
        assert record["name"] == "Pipeline C" and record["description"] == "Made on another machine."
        assert [s["commit"] for s in record["snapshots"]] == [taken.commit]
        page = site / "cb" / "pipelines" / "pipeline_c.html"
        text = page.read_text(encoding="utf-8")
        assert "stored snapshots" in text
        assert "not on this machine" not in text.lower()
        links = _links(page)
        assert links and all(_resolves(page, h) for h in links)
        versions_page = (site / "cb" / "versions.html").read_text(encoding="utf-8")
        assert "stored snapshots" in versions_page
        assert "not on this machine" not in versions_page
        assert "pipeline_c" in (site / "cb" / "pipelines.html").read_text(encoding="utf-8")
        assert "pipeline_c" in (site / "cb" / "diagnostics.html").read_text(encoding="utf-8")

    def test_one_with_no_snapshot_says_so(self, catalog, monkeypatch):
        root, first, second = catalog
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest.setdefault("pipelines", {})["acme/nowhere"] = {}
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        _build(root, monkeypatch)
        assert not (root / "docs/cb/pipelines/acme--nowhere.html").exists()
        index = json.loads((root / "docs/index.json").read_text(encoding="utf-8"))
        assert not any(r["id"] == "acme/nowhere" for r in index["records"])

    def test_the_catalogs_other_commands_pass_it_by(self, catalog, monkeypatch):
        root, first, second = catalog
        monkeypatch.chdir(root)
        before = CliRunner().invoke(main, ["check", "--skip-outputs"])
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest.setdefault("pipelines", {})["acme/nowhere"] = {}
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        from chartbook.manifest import get_pipeline_ids, load_manifest

        loaded = load_manifest(root)
        assert "acme/nowhere" not in get_pipeline_ids(loaded)
        after = CliRunner().invoke(main, ["check", "--skip-outputs"])
        # The fixture's own missing fields are said as before; the entry adds nothing to check
        assert after.exit_code == before.exit_code == 1 and "acme/nowhere" not in after.output
        assert after.output.count("required by") == before.output.count("required by")

    def test_with_mkdocs_too(self, catalog, tmp_path, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = catalog
        self._elsewhere(tmp_path)
        manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
        manifest.setdefault("pipelines", {})["pipeline_c"] = {}
        manifest["project"]["writer"] = "mkdocs"
        (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        result = _build(root, monkeypatch)
        assert "contains a link" not in result.output, result.output
        page = root / "docs" / "cb" / "pipelines" / "pipeline_c.html"
        assert _links(page) and all(_resolves(page, h) for h in _links(page))
        # Its dataframes are listed beside the catalog's own, each linked to its page in the newest version
        listing = root / "docs" / "cb" / "dataframes.html"
        assert "Dataframe 0" in listing.read_text(encoding="utf-8")
        assert any("pipeline_c/" in h and h.endswith("dataframe_0.html") and _resolves(listing, h) for h in re.findall(r'href="([^"#]+)"', listing.read_text(encoding="utf-8")))

    def test_its_assets_are_listed_from_its_newest_snapshot(self, catalog, tmp_path, monkeypatch):
        """Found by a new-user test: a colleague's pipeline had a page and versions, and none of its
        dataframes in the catalog's Dataframes list or in `chartbook ls`."""
        root, first, second = catalog
        taken = self._elsewhere(tmp_path)
        _show_from_the_store(root)
        _build(root, monkeypatch)
        site = root / "docs"
        record = next(r for r in json.loads((site / "index.json").read_text(encoding="utf-8"))["records"] if r["id"] == "pipeline_c")
        assert record["assets"] == ["pipeline_c:chart/chart_0_0", "pipeline_c:dataframe_0"]
        assert record["asset_names"] == {"pipeline_c:chart/chart_0_0": "Chart 0-0", "pipeline_c:dataframe_0": "Dataframe 0"}
        listing = site / "cb" / "dataframes.html"
        assert "Dataframe 0" in listing.read_text(encoding="utf-8")
        linked = [h for h in re.findall(r'href="([^"#]+)"', listing.read_text(encoding="utf-8")) if h.endswith("dataframes/pipeline_c/dataframe_0.html")]
        assert linked and all(_resolves(listing, h) for h in linked)
        readme = site / "cb" / "pipelines" / "pipeline_c.html"
        assert "Chart 0-0" in readme.read_text(encoding="utf-8")
        assert all(_resolves(readme, h) for h in _links(readme))
        # And `chartbook ls`, in the tree and the flat lists
        tree = CliRunner().invoke(main, ["ls", "--catalog", str(root)])
        assert tree.exit_code == 0, tree.output
        assert "[pipeline] pipeline_c: (stored snapshots)" in tree.output
        assert "  [dataframe] pipeline_c:dataframe_0: Dataframe 0\n  [chart] pipeline_c:chart/chart_0_0: Chart 0-0" in tree.output
        flat = CliRunner().invoke(main, ["ls", "--catalog", str(root), "dataframes"])
        assert "pipeline_c:dataframe_0: Dataframe 0" in flat.output
        assert "pipeline_c:chart/chart_0_0: Chart 0-0" in CliRunner().invoke(main, ["ls", "--catalog", str(root), "charts"]).output


    def test_ls_writes_references_as_everything_else_does(self, catalog):
        """Found by a new-user test: `first_pipeline/rates` reads as a scoped pipeline ID."""
        root, first, second = catalog
        tree = CliRunner().invoke(main, ["ls", "--catalog", str(root)]).output
        assert "  [dataframe] pipeline_a:dataframe_0: Dataframe 0" in tree
        assert "  [chart] pipeline_a:chart/chart_0_0: Chart 0-0" in tree
        assert "pipeline_a/" not in tree
        assert "pipeline_b:dataframe_0: Dataframe 0" in CliRunner().invoke(main, ["ls", "--catalog", str(root), "dataframes"]).output
        charts = CliRunner().invoke(main, ["ls", "--catalog", str(root), "charts"]).output
        assert "pipeline_b:chart/chart_0_0: Chart 0-0" in charts and "pipeline_b/" not in charts
        single = CliRunner().invoke(main, ["ls", "--catalog", str(root / "pipelines" / "pipeline_a")]).output
        assert "  [dataframe] pipeline_a:dataframe_0: Dataframe 0" in single


def _elsewhere_with(tmp_path, asset_name: str = "", **project) -> "snapshot.Snapshot":
    """A pipeline `pipeline_c` snapshotted elsewhere with these `[project]` fields (and this name for
    its dataframe and its chart), its folder then gone."""
    import shutil

    from tests.fixtures import create_pipeline_project

    repository = tmp_path.resolve() / "elsewhere"
    folder = create_pipeline_project(repository / "pipeline_c", pipeline_id="pipeline_c", pipeline_name="Pipeline C")
    manifest = tomli.loads((folder / "chartbook.toml").read_text(encoding="utf-8"))
    manifest["project"].update(project)
    if asset_name:
        manifest["dataframes"]["dataframe_0"]["name"] = manifest["charts"]["chart_0_0"]["name"] = asset_name
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    taken = snapshot.make(folder).snapshot
    remove_tree(repository)
    return taken


def test_a_version_that_did_not_build_an_asset_has_a_site_that_says_so(tmp_path):
    """A snapshot holds what its build made; what it did not make was not built in that version.

    `chartbook docs build` there used to stop on it as built in part, and the
    catalog's link to the version said the error's last line, advice to run
    `chartbook build` or to edit chartbook.toml, which are no use for a
    past version.
    """
    from tests.fixtures import create_pipeline_project

    repository = tmp_path.resolve() / "elsewhere"
    folder = create_pipeline_project(repository / "pipeline_c", pipeline_id="pipeline_c", pipeline_name="Pipeline C")
    (folder / "_output" / "charts" / "chart_0_0.html").unlink()
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    taken = snapshot.make(folder).snapshot
    rendered = versions.render(taken)
    assert rendered.built, rendered.why
    chart = rendered.folder / "_static" / "pipeline_c" / "chart_0_0.html"
    assert "Not built in this version" in chart.read_text(encoding="utf-8")
    pages = "".join(p.read_text(errors="replace", encoding="utf-8") for p in rendered.folder.rglob("*.html"))
    assert "chartbook build" not in pages
    assert "update the paths" not in pages


def _show_from_the_store(root: Path, pipeline_id: str = "pipeline_c", **settings) -> None:
    manifest = tomli.loads((root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).read_text(encoding="utf-8"))
    manifest.setdefault("pipelines", {})[pipeline_id] = {}
    manifest["project"].update(settings)
    (root / ("catalog.toml" if (root / "catalog.toml").is_file() else "chartbook.toml")).write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")


class _Markup:
    """The elements and attributes of a page, as a browser would read them."""

    def __init__(self, page: Path):
        from html.parser import HTMLParser

        self.tags, self.scripts = [], []
        markup = self

        class Reader(HTMLParser):
            in_script = False

            def handle_starttag(self, tag, attrs):
                markup.tags.append((tag, dict(attrs)))
                self.in_script = tag == "script"

            def handle_endtag(self, tag):
                self.in_script = False

            def handle_data(self, data):
                if self.in_script:
                    markup.scripts.append(data)

        Reader().feed(page.read_text(encoding="utf-8"))


class TestWhatTheStoreOnlyReviewFound:
    """What a pipeline's snapshot says of it reaches the catalog's own pages as text, never as markup."""

    HOSTILE = {
        "name": "C\n# <img src=x onerror=alert(2)></title><script>alert(7)</script>",
        "description": (
            "Hi <script>alert(1)</script>\n"
            "```{include} SECRET\n```\n"
            ":::{include} SECRET\n:::\n"
            "{eval-rst}`x` [click](javascript:alert(3)) | a | b |"
        ),
        "maintainer": "<b onmouseover=alert(4)>M</b>",
        "repo_url": "javascript:alert(5)",
        "site_url": 'https://example.org/" onmouseover="alert(6)',
    }

    def _hostile(self, tmp_path) -> tuple[dict, Path]:
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-TEXT", encoding="utf-8", newline="\n")
        fields = {k: v.replace("SECRET", str(secret)) for k, v in self.HOSTILE.items()}
        return fields, secret

    def _no_markup_from_the_store(self, page: Path) -> None:
        # Not in the file at all, as markup or as text a title or a theme could decode
        written = page.read_text(encoding="utf-8")
        for planted in ("<script>alert", "<img src=x", "</title><script", "<b onmouseover"):
            assert planted not in written, (page, planted)
        read = _Markup(page)
        assert not any("alert(" in script for script in read.scripts), page
        for tag, attributes in read.tags:
            assert not (tag == "img" and attributes.get("src") == "x"), (page, tag, attributes)
            assert "onmouseover" not in attributes and "onerror" not in attributes, (page, tag, attributes)
            assert not (attributes.get("href") or "").lower().startswith("javascript"), (page, attributes)

    def test_the_catalogs_pages_show_it_as_text(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        fields, secret = self._hostile(tmp_path)
        _elsewhere_with(tmp_path, **fields)
        _show_from_the_store(root)
        _build(root, monkeypatch)
        site = root / "docs"
        own = [
            site / "cb" / "pipelines" / "pipeline_c.html",
            site / "cb" / "pipelines.html",
            site / "cb" / "versions.html",
            site / "index.html",
        ]
        for page in own:
            self._no_markup_from_the_store(page)
        readme = own[0].read_text(encoding="utf-8")
        # Shown as written, on one line, HTML's own characters by look-alikes
        assert "Hi ‹script›alert(1)‹/script›" in readme
        assert "‹b onmouseover=alert(4)›M‹/b›" in readme
        # Nor in the search index, whose titles Sphinx's search sets into HTML
        self._no_markup_from_the_store(site / "searchindex.js")
        # Not a web address: no link at all
        assert "Repository:" not in readme and "Web page:" not in readme
        assert not any("TOP-SECRET-TEXT" in page.read_text(errors="ignore", encoding="utf-8") for page in site.rglob("*.html"))

    def test_and_with_mkdocs(self, catalog, tmp_path, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        root, first, second = catalog
        fields, secret = self._hostile(tmp_path)
        _elsewhere_with(tmp_path, **fields)
        _show_from_the_store(root, writer="mkdocs")
        _build(root, monkeypatch)
        site = root / "docs"
        for page in [site / "cb" / "pipelines" / "pipeline_c.html", site / "cb" / "pipelines.html", site / "index.html",
                     site / "search" / "search_index.json"]:
            if page.exists():
                self._no_markup_from_the_store(page)
        # The page title, which the theme decodes and writes unescaped
        title = (site / "cb" / "pipelines" / "pipeline_c.html").read_text(encoding="utf-8").split("<title>", 1)[1].split("</title>", 1)[0]
        assert "<" not in title and "‹" in title
        assert not any("TOP-SECRET-TEXT" in page.read_text(errors="ignore", encoding="utf-8") for page in site.rglob("*.html"))

    @pytest.mark.parametrize("writer", ["sphinx", "mkdocs"])
    def test_an_assets_name_is_text_too(self, catalog, tmp_path, monkeypatch, writer):
        if writer == "mkdocs":
            pytest.importorskip("mkdocs")
            pytest.importorskip("material")
        root, first, second = catalog
        _elsewhere_with(tmp_path, asset_name="D <script>alert(8)</script> [x](javascript:alert(9)) <b onmouseover=alert(4)>\x1b[31m")
        _show_from_the_store(root, writer=writer)
        _build(root, monkeypatch)
        site = root / "docs"
        for page in (site / "cb" / "dataframes.html", site / "cb" / "pipelines" / "pipeline_c.html"):
            self._no_markup_from_the_store(page)
            # As a browser shows it: one writer leaves the character references in the page as written
            assert "D ‹script›alert(8)‹/script›" in html.unescape(page.read_text(encoding="utf-8")), page
            assert "\x1b" not in page.read_text(encoding="utf-8")
        listed = CliRunner().invoke(main, ["ls", "--catalog", str(root)]).output
        assert "[dataframe] pipeline_c:dataframe_0: D <script>alert(8)</script>" in listed and "\x1b" not in listed

    def test_a_web_address_is_a_link(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        _elsewhere_with(tmp_path, repo_url="https://github.com/acme/pipeline_c", site_url="https://acme.org/c?a=1&b=2#top")
        _show_from_the_store(root)
        _build(root, monkeypatch)
        read = _Markup(root / "docs" / "cb" / "pipelines" / "pipeline_c.html")
        hrefs = [attributes.get("href") for tag, attributes in read.tags if tag == "a"]
        assert "https://github.com/acme/pipeline_c" in hrefs and "https://acme.org/c?a=1&b=2#top" in hrefs

    @pytest.mark.parametrize(
        "content",
        ['[1, 2]', '{"records": 5}', '{"records": [5, "x", null]}', "[" * 100000 + "]" * 100000,
         '{"records": [{"kind": "Pipeline", "id": "pipeline_c", "description": 5, "name": ["x"]}]}'],
        ids=["a-list", "records-a-number", "records-not-tables", "too-deep", "fields-not-text"],
    )
    def test_a_stored_index_of_any_shape_is_no_description(self, catalog, tmp_path, monkeypatch, content):
        import os
        import stat

        root, first, second = catalog
        taken = _elsewhere_with(tmp_path)
        held = default_store().files(taken.index["content_hash"], name="index.json").one.location.parent
        os.chmod(held, stat.S_IRWXU)
        os.chmod(held / "index.json", stat.S_IRUSR | stat.S_IWUSR)
        (held / "index.json").write_text(content, encoding="utf-8", newline="\n")
        _show_from_the_store(root)
        _build(root, monkeypatch)
        record = next(r for r in json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))["records"] if r["id"] == "pipeline_c")
        assert record["name"] == "pipeline_c" and "description" not in record

    def _held(self, taken) -> Path:
        import os
        import stat

        held = default_store().files(taken.index["content_hash"], name="index.json").one.location.parent
        os.chmod(held, stat.S_IRWXU)
        os.chmod(held / "index.json", stat.S_IRUSR | stat.S_IWUSR)
        return held

    def _shown(self, root: Path, monkeypatch) -> dict:
        _show_from_the_store(root)
        _build(root, monkeypatch)
        return next(r for r in json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))["records"] if r["id"] == "pipeline_c")

    def test_a_stored_index_is_not_read_through_a_link(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        taken = _elsewhere_with(tmp_path)
        held = self._held(taken)
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"records": [{"kind": "Pipeline", "id": "pipeline_c", "description": "From outside."}]}), encoding="utf-8", newline="\n")
        (held / "index.json").unlink()
        (held / "index.json").symlink_to(outside)
        assert "description" not in self._shown(root, monkeypatch)

    def test_nor_past_a_limit(self, catalog, tmp_path, monkeypatch):
        root, first, second = catalog
        _elsewhere_with(tmp_path, description="Long enough.")
        monkeypatch.setattr(snapshot, "STORED_INDEX_LIMIT", 100)
        assert "description" not in self._shown(root, monkeypatch)

    @pytest.mark.parametrize("blank", ["\u200b\u200b \u2028", "\u3164", "\u2800\u2800", "\u0301\u0301", "\uffa0 \u115f"])
    def test_a_name_of_nothing_visible_is_no_name(self, catalog, tmp_path, monkeypatch, blank):
        root, first, second = catalog
        _elsewhere_with(tmp_path, name=blank)
        record = self._shown(root, monkeypatch)
        assert record["name"] == "pipeline_c"
        page = (root / "docs" / "cb" / "pipelines.html").read_text(encoding="utf-8")
        assert not re.search(r"<h2[^>]*>\s*(<a [^>]*>[^<]*</a>)?\s*</h2>", page)

    def test_the_description_is_the_linked_snapshots(self, catalog, tmp_path, monkeypatch):
        """The newest snapshot is the one described and the one linked, even when it has no index."""
        import dataclasses

        root, first, second = catalog
        taken = _elsewhere_with(tmp_path, description="The older one.")
        later = dataclasses.replace(taken, made_at="2099-01-01T00:00:00Z", index=None)
        snapshot._write(later, default_store())
        _show_from_the_store(root)
        _build(root, monkeypatch)
        record = next(r for r in json.loads((root / "docs" / "index.json").read_text(encoding="utf-8"))["records"] if r["id"] == "pipeline_c")
        assert record["snapshots"][0]["made_at"] == "2099-01-01T00:00:00Z"
        assert "description" not in record


class TestTheTextAndLinkChecks:
    @pytest.mark.parametrize(
        "written, shown",
        [("Rates\n and  more", "Rates and more"), ("\u3164", ""), ("\u0301", ""), ("R² CO₂ ｒａｔｅｓ", "R² CO₂ ｒａｔｅｓ"), (None, ""), ("a\ud800b", "a b")],
    )
    def test_a_plain_line(self, written, shown):
        from chartbook.identity import plain_line

        assert plain_line(written) == shown

    def test_text_is_one_line_with_no_markup(self):
        from chartbook.writers.sphinx import _as_text

        assert _as_text("Rates\n\n  and *more*") == "Rates and &#42;more&#42;"
        assert _as_text("<a>") == "‹a›"
        assert _as_text("{include}`x`") == "&#123;include&#125;‘x‘"
        assert _as_text("""A & B's "x" """) == "A and B’s ”x”"
        assert _as_text("A&B") == "A and B"
        # Anything that is not HTML's own stays as written
        assert _as_text("R² CO₂ x⁻¹ ½ ™ №") == "R² CO₂ x⁻¹ ½ ™ №"
        assert _as_text("Zürich ±") == "Zürich ±"
        assert _as_text(None) == "" and _as_text(5) == ""
        assert _as_text("a\x00b‮c") == "a b c"
        # Decoded again, and normalized (NFKC) besides, nothing of HTML's own is there
        import html
        import unicodedata

        for planted in ("</title><script>&lt;'\"`", "＜script＞＆lt;＂＇｀", "﹤img﹥﹠", "&amp;lt;", "≮img≯"):
            for form in ("NFKC", "NFKD"):
                shown = unicodedata.normalize(form, html.unescape(html.unescape(_as_text(planted))))
                assert not set(shown) & set("<>&'\"`"), (planted, form, shown)

    def test_long_text_costs_nothing(self):
        import time

        from chartbook.identity import plain_line

        started = time.perf_counter()
        assert len(plain_line("\ufdfa" * 2_000_000, 200)) == 200
        assert time.perf_counter() - started < 1
        # Read as far as the length kept, spaces not counted
        assert plain_line(" " * 800 + "Visible name", 200) == "Visible name"
        assert len(plain_line(("a" + " " * 9) * 1000, 2000)) >= 1999

    @pytest.mark.parametrize(
        "written, shown",
        [
            ("https://github.com/acme/rates", "https://github.com/acme/rates"),
            ("  http://acme.org:8080/a?b=1&c=2#f  ", "http://acme.org:8080/a?b=1&c=2#f"),
            ("https://user:token@github.com/acme/rates", "https://github.com/acme/rates"),
            ("javascript:alert(1)", ""),
            ("JaVaScRiPt://acme.org/%0aalert(1)", ""),
            ('https://acme.org/" onmouseover="alert(1)', ""),
            ("https://acme.org/a b", ""),
            ("https://acme.org/(x)", ""),
            ("https://acme.org/<script>", ""),
            ("ftp://acme.org/x", ""),
            ("httpſ://acme.org/x", ""),
            ("https://acme.org/\u212a", ""),
            ("HTTPS://Acme.org/X", "HTTPS://Acme.org/X"),
            ("https://", ""),
            ("https://acme.org/" + "a" * 3000, ""),
            (5, ""),
            (None, ""),
        ],
    )
    def test_a_link_is_a_plain_web_address(self, written, shown):
        from chartbook.identity import web_link

        assert web_link(written) == shown




class TestATagIsAVersionsName:
    def test_the_versions_page_says_it(self, catalog, monkeypatch):
        root, first, second = catalog
        repository = root.parent
        a = root / "pipelines" / "pipeline_a"
        data = next((a / "_data").rglob("*.parquet"))
        pl.DataFrame({"date": ["2025-02-01"], "value": [1.5]}).write_parquet(data)
        _commit(repository, "Release")
        _git(repository, "tag", "release-9")
        tagged = snapshot.make(a).snapshot
        assert tagged.tags == ["release-9"]
        _build(root, monkeypatch)
        page = (root / "docs" / "cb" / "versions.html").read_text(encoding="utf-8")
        assert "tagged" in page and "<code>release-9</code>" in page
