"""Pipelines enter catalogs by snapshot; stores enter with store add."""
import tomli
from click.testing import CliRunner
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.test_several_stores import configure, pipeline
from chartbook import snapshot


def test_catalog_add_explains_replacement():
    result = CliRunner().invoke(main, ["catalog", "add", "../pipeline"])
    assert result.exit_code == 2
    assert "store add" in result.output and "snapshot" in result.output


def test_store_add_preserves_comments_and_discovers_snapshots(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(tmp_path / "mine")}})
    path.write_text("# Keep my catalog notes\n" + path.read_text())
    folder = pipeline(tmp_path)
    shared = FolderStore(tmp_path / "shared")
    snapshot.make(folder, shared)
    result = CliRunner().invoke(main, ["store", "add", "shared", str(shared), "--read-only", "--catalog", str(path)])
    assert result.exit_code == 0, result.output
    assert "acme/upstream" in result.output
    assert path.read_text().startswith("# Keep my catalog notes")
    assert tomli.loads(path.read_text())["stores"]["shared"]["read_only"] is True


def test_store_remove_leaves_files_and_comments(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "kept.txt").write_text("mine")
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(tmp_path / "mine")}, "shared": {"url": str(shared)}})
    path.write_text("# Keep my catalog notes\n" + path.read_text())
    result = CliRunner().invoke(main, ["store", "remove", "shared", "--catalog", str(path)])
    assert result.exit_code == 0, result.output
    assert "untouched" in result.output
    assert (shared / "kept.txt").read_text() == "mine"
    assert path.read_text().startswith("# Keep my catalog notes")
    assert "shared" not in tomli.loads(path.read_text())["stores"]


def test_store_add_duplicate_keeps_original_file(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(shared)}})
    before = path.read_bytes()
    result = CliRunner().invoke(main, ["store", "add", "duplicate", str(shared), "--catalog", str(path)])
    assert result.exit_code == 1
    assert path.read_bytes() == before


def test_store_add_refuses_an_unrelated_folder_without_editing_catalog(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, {"mine": {"url": str(tmp_path / "mine")}})
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "notes.txt").write_text("Keep this folder")
    before = path.read_bytes()
    result = CliRunner().invoke(main, ["store", "add", "other", str(unrelated)])
    assert result.exit_code == 1 and "not a store" in result.output
    assert path.read_bytes() == before


def test_store_edits_follow_the_configured_catalog(tmp_path, monkeypatch):
    from chartbook import config
    import tomli_w
    home = tmp_path / "home"
    home.mkdir()
    team = tmp_path / "team"
    team.mkdir()
    catalog = team / "catalog.toml"
    catalog.write_text("# Team notes\n[stores.mine]\nurl='../mine'\n")
    monkeypatch.delenv("CHARTBOOK_STORE", raising=False)
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    config.write_global_settings({"catalog": {"path": str(catalog)}})
    shared = tmp_path / "shared"
    shared.mkdir()
    result = CliRunner().invoke(main, ["store", "add", "shared", str(shared)])
    assert result.exit_code == 0, result.output
    assert "shared" in tomli.loads(catalog.read_text())["stores"]
    assert catalog.read_text().startswith("# Team notes")
    assert not (home / "catalog.toml").exists()
