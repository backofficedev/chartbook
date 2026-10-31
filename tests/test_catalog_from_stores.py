"""A catalog's inputs survive removal of every working repository."""
import json
import pytest

from chartbook import index, snapshot
from chartbook.manifest import load_manifest
from chartbook.store import FolderStore
from tests.test_several_stores import configure, pipeline


def test_catalog_discovers_stored_pipelines_and_ignores_working_folders(tmp_path, monkeypatch):
    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    snapshot.make(folder, store)
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    from tests.fixtures import remove_tree
    remove_tree(folder)
    manifest = load_manifest(path.parent)
    assert manifest["pipelines"] == {}
    assert manifest["store_pipelines"] == ["acme/upstream"]
    built = index.build_index(manifest)
    record = next(r for r in built["records"] if r["kind"] == "Pipeline")
    assert record["snapshots"][0]["store"] == "mine"
    assert record["assets"]


def test_catalog_site_builds_from_stores(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from chartbook.cli import main
    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    snapshot.make(folder, store)
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    from tests.fixtures import remove_tree
    remove_tree(folder)
    result = CliRunner().invoke(main, ["catalog", "build", "-f", "--clean"])
    assert result.exit_code == 0, result.output
    assert (path.parent / "docs" / "index.html").is_file()
    assert (path.parent / "docs" / "cb" / "versions.html").is_file()


from tests.test_tables_across_pipelines import work as table_pipeline


def test_tables_and_queries_render_from_parquet_without_database(table_pipeline, tmp_path, monkeypatch):
    from click.testing import CliRunner
    from chartbook.cli import main
    from chartbook.store import default_store
    from tests.fixtures import remove_tree
    rates, _ = table_pipeline
    taken = snapshot.make(rates).snapshot
    stored = snapshot._stored_records(taken, default_store())
    remove_tree(rates)
    laid = snapshot.materialize(taken, tmp_path / "laid")
    manifest = load_manifest(laid.folder)
    assert manifest["dataframes"]["curve"]["path"] == "_chartbook/tables/curve.parquet"
    assert (laid.folder / "_chartbook/tables/slopes.parquet").is_file()
    result = CliRunner().invoke(main, ["docs", "build", str(laid.folder / "docs"), "--project-dir", str(laid.folder), "-f"])
    assert result.exit_code == 0, result.output
    built = json.loads((laid.folder / "docs/index.json").read_text())
    curve = next(r for r in built["records"] if r["id"] == "acme/rates:curve")
    assert curve["columns"] and curve["row_count"] == 2
    prior = next(r for r in stored if r["id"] == curve["id"])
    if prior.get("location", {}).get("modified_at"):
        assert curve["location"]["modified_at"] == prior["location"]["modified_at"]


def test_store_catalog_records_match_published_schemas(tmp_path, monkeypatch):
    import jsonschema
    from pathlib import Path
    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    snapshot.make(folder, store)
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    built = index.published(index.build_index(load_manifest(path.parent)))
    schemas = Path(__file__).parents[1] / "src/chartbook/schemas/chartbook"
    jsonschema.validate(built, json.loads((schemas / "index/v1.json").read_text()))
    for record in built["records"]:
        jsonschema.validate(record, json.loads((schemas / "v1" / (record["kind"] + ".json")).read_text()))
    assert built["records"][0]["pipelines"] == ["acme/upstream"]
    assert "url" not in built["stores"][0]


def test_catalog_reads_no_working_members_and_needs_no_member_trust(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from chartbook.cli import main
    from chartbook import config
    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    snapshot.make(folder, store)
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
    result = CliRunner().invoke(main, ["catalog", "build", "-f"])
    assert result.exit_code == 0, result.output
    assert "Trust" not in result.output and config.read_trust() == []
    for words, hint in ((["run"], "stored snapshots"), (["check"], "Diagnostics"), (["trust", "--members"], "no working members")):
        result = CliRunner().invoke(main, [*words, "--project-dir", str(path.parent)] if words[0] != "trust" else words)
        assert result.exit_code != 0
        assert hint in result.output
    assert config.read_trust() == []


def test_run_and_plan_refuse_catalogs(tmp_path):
    import pytest
    from chartbook import run
    (tmp_path / "catalog.toml").write_text('[project]\nname="Catalog"\n[stores.mine]\nurl="store"\n')
    for action in (run.plan, run.run):
        with pytest.raises(run.RunError, match="A catalog lists stored snapshots"):
            action(tmp_path)


def test_repository_note_selects_the_catalog_read_as_well_as_the_hub(tmp_path, monkeypatch):
    import pytest
    import polars as pl
    import tomli
    import tomli_w
    from chartbook import data
    from tests.test_model_versions import _git
    first = pipeline(tmp_path / "first")
    second = pipeline(tmp_path / "second")
    _git(second, "commit", "--amend", "--quiet", "-m", "Unrelated repository")
    for folder, owner, number in ((first, "one", 1), (second, "two", 2)):
        _git(folder, "remote", "add", "origin", f"https://github.com/{owner}/upstream")
        path = next((folder / "_data").rglob("*.parquet"))
        pl.DataFrame({"chosen": [number]}).write_parquet(path)
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Data")
    a, b = FolderStore(tmp_path / "a"), FolderStore(tmp_path / "b")
    snapshot.make(first, a)
    snapshot.make(second, b)
    path = configure(tmp_path, monkeypatch, {"one": {"url": str(a)}, "two": {"url": str(b)}})
    with pytest.raises(ValueError, match="Several repositories"):
        index.build_index(load_manifest(path.parent))
    doc = tomli.loads(path.read_text())
    doc["pipelines"] = {"acme/upstream": {"repository": "https://github.com/one/upstream"}}
    path.write_text(tomli_w.dumps(doc))
    monkeypatch.chdir(path.parent)
    assert data.load(dataframe="dataframe_0", pipeline="acme/upstream", catalog_path=path).collect()["chosen"].to_list() == [1]
    built = index.build_index(load_manifest(path.parent))
    own = next(r for r in built["records"] if r["id"] == "acme/upstream")
    assert len(own["snapshots"]) == 1
    assert own["snapshots"][0]["store"] == "one"


@pytest.mark.parametrize("note", [{"path": "../work"}, {"members": ["*"]}, {"disabled": "yes"}, "../work", 5])
def test_catalog_notes_cannot_register_working_folders(tmp_path, note):
    import tomli_w
    (tmp_path / "catalog.toml").write_text(tomli_w.dumps({"pipelines": {"acme/upstream": note}}))
    with pytest.raises(ValueError, match="accepts only|boolean"):
        load_manifest(tmp_path)


def test_legacy_catalog_requires_explicit_migration(tmp_path):
    (tmp_path / "chartbook.toml").write_text('[project]\ntype="catalog"\n[pipelines]\n')
    with pytest.raises(ValueError, match="chartbook catalog migrate"):
        load_manifest(tmp_path)


def test_pipeline_hub_lists_tags_and_who_pins_each_version(tmp_path, monkeypatch):
    from chartbook.writers.sphinx import SphinxWriter
    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    taken = snapshot.make(folder, store).snapshot
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    built = index.build_index(load_manifest(path.parent))
    own = next(r for r in built["records"] if r["id"] == taken.pipeline)
    own["snapshots"][0]["tags"] = ["v1"]
    built["records"].append({"kind": "Pipeline", "id": "acme/downstream", "location": {"kind": "store"}, "dependencies": [{"id": taken.pipeline, "location": {"commit": taken.commit}, "snapshot": taken.made_at}]})
    page = SphinxWriter(built, theme="catalog").pipeline_page(taken.pipeline)
    import html
    shown = html.unescape(page)
    assert "tagged v1" in shown and "pinned by acme/downstream" in shown


@pytest.mark.parametrize("backend", ["sphinx", "mkdocs"])
def test_dataframe_hub_keeps_versions_and_changes_out_of_the_dictionary(tmp_path, monkeypatch, backend):
    import html
    import re
    from chartbook.writers.sphinx import SphinxWriter
    from chartbook.writers.mkdocs import MkDocsWriter

    folder = pipeline(tmp_path)
    store = FolderStore(tmp_path / "store")
    snapshot.make(folder, store, made_at="2026-01-01T00:00:00Z")
    from tests.test_model_versions import _git
    _git(folder, "commit", "--allow-empty", "-m", "New version, same data")
    snapshot.make(folder, store, made_at="2026-01-02T00:00:00Z")
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(store)}})
    built = index.build_index(load_manifest(path.parent))
    record = next(r for r in built["records"] if r["kind"] == "Dataframe")
    writer = (SphinxWriter if backend == "sphinx" else MkDocsWriter)(built, theme="catalog")
    page = html.unescape(writer.page(record))
    sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", page, re.M | re.S))
    dictionary = sections["Current data dictionary"]
    versions = sections["Versions"]
    assert "| Column | Type |" in dictionary
    assert "versions/" not in dictionary and "Nothing changed" not in dictionary
    assert len(record["snapshots"]) == 2
    for entry in record["snapshots"]:
        assert entry["made_at"] in versions
        assert entry["commit"][:7] in versions
        if entry.get("changes"):
            assert entry["changes"] in versions
    assert versions.count('<a href="') == 2
    assert "## Snapshot history" not in page
