from pathlib import Path
import pytest

from chartbook import links, snapshot
from chartbook.resolve import resolve
from chartbook.store import FolderStore
from tests.test_several_stores import pipeline


def test_explicit_link_reads_working_files_and_snapshot_refuses(tmp_path):
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\n"acme/upstream"={}\n')
    links.add(consumer, "acme/upstream", upstream)
    raw = __import__('tomli').loads((upstream / "chartbook.toml").read_text())
    name, entry = next(iter(raw["dataframes"].items()))
    with pytest.warns(links.LinkedDependencyWarning, match="pin is not in use"):
        location = resolve(f"acme/upstream:{name}", start_dirs=[consumer])
    assert location.path == upstream / entry["path"]
    assert not (consumer / "chartbook.lock").exists()
    with pytest.raises(snapshot.SnapshotError, match="chartbook.links.toml"):
        snapshot.make(consumer, FolderStore(tmp_path / "store"))


def test_ci_and_frozen_ignore_links(tmp_path, monkeypatch):
    (tmp_path / links.NAME).write_text('"acme/upstream"="../absent"\n')
    monkeypatch.setenv("CI", "true")
    assert links.read(tmp_path) == {}
    assert links.read(tmp_path, active=False)
    monkeypatch.delenv("CI")
    monkeypatch.setenv("CHARTBOOK_FROZEN", "1")
    assert links.read(tmp_path) == {}


def test_link_checks_identity(tmp_path):
    upstream = pipeline(tmp_path)
    with pytest.raises(ValueError, match="declares"):
        links.add(tmp_path, "acme/other", upstream)


def test_an_unlinked_working_dependency_is_never_read(tmp_path, monkeypatch):
    from chartbook.errors import AssetNotPinnedError
    import tomli
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\n"acme/upstream"={path="../upstream"}\n')
    name = next(iter(tomli.loads((upstream / "chartbook.toml").read_text())["dataframes"]))
    with pytest.raises(AssetNotPinnedError, match="chartbook link"):
        resolve(f"acme/upstream:{name}", start_dirs=[consumer])


def test_run_snapshot_with_links_stops_before_executing(tmp_path):
    from chartbook import run
    (tmp_path / links.NAME).write_text("")
    with pytest.raises(run.RunError, match="chartbook.links.toml"):
        run.run(tmp_path, snapshot=True)


def test_link_by_canonical_id_overrides_a_path_dependency_alias(tmp_path):
    upstream = pipeline(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\nyc={path="../upstream"}\n')
    links.add(consumer, "acme/upstream", upstream)
    with pytest.warns(links.LinkedDependencyWarning):
        result = resolve("yc:dataframe_0", start_dirs=[consumer])
    assert result.path.is_file() and upstream in result.path.parents
