"""Federation above the unchanged folder and plugin store contracts."""
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, snapshot
from chartbook.cli import main
from chartbook.multi_store import Stores
from chartbook.store import FolderStore, ReadOnlyStoreError, StoreUnreachableError
from tests.fixtures import create_pipeline_project
from tests.test_model_versions import _git


def configure(tmp_path, monkeypatch, definitions):
    monkeypatch.delenv("CHARTBOOK_STORE", raising=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    path = home / "catalog.toml"
    path.write_text(tomli_w.dumps({"project": {"name": "Catalog"}, "stores": definitions}))
    return path


def pipeline(tmp_path):
    folder = create_pipeline_project(tmp_path / "upstream", pipeline_id="acme/upstream")
    _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Initial")
    return folder


def test_reads_every_store_and_newest_wins(tmp_path, monkeypatch):
    folder = pipeline(tmp_path)
    a, b = FolderStore(tmp_path / "a"), FolderStore(tmp_path / "b")
    first = snapshot.make(folder, a, made_at="2026-01-01T00:00:00Z").snapshot
    second = snapshot.make(folder, b, made_at="2026-01-02T00:00:00Z").snapshot
    configure(tmp_path, monkeypatch, {"one": {"url": str(a)}, "two": {"url": str(b)}})
    stores = Stores.configured()
    found, errors = snapshot.readable_snapshots(stores)
    assert not errors
    assert [t.made_at for t in found] == [first.made_at, second.made_at]
    assert stores.name_of(second.path) == "two"
    assert stores.has(next(iter(second.hashes())))
    assert stores.get(next(iter(second.hashes()))).exists()


def test_override_is_the_only_store(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, {"real": {"url": str(tmp_path / "real")}})
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "scratch"))
    stores = Stores.configured()
    assert [str(s) for s in stores.in_order()] == [str(tmp_path / "scratch")]


def test_duplicate_locations_and_invalid_options(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, {"one": {"url": "../same"}, "two": {"url": "../same/."}})
    with pytest.raises(ValueError, match="already listed"):
        Stores.configured()
    configure(tmp_path, monkeypatch, {"one": {"url": "../same", "read_only": "yes"}})
    with pytest.raises(ValueError, match="boolean"):
        Stores.configured()


def test_missing_named_store_is_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    configure(tmp_path, monkeypatch, {"one": {"url": str(tmp_path / "default")}, "two": {"url": str(missing)}})
    stores = Stores.configured()
    with pytest.warns(UserWarning, match="unreachable"):
        assert stores.all_snapshot_files() == []
    with pytest.raises(StoreUnreachableError):
        stores.for_writing("acme/upstream", ["two"])
    assert not missing.exists()


def test_routes_and_fanout_preserve_snapshot(tmp_path, monkeypatch):
    folder = pipeline(tmp_path)
    second = tmp_path / "two"
    second.mkdir()
    configure(tmp_path, monkeypatch, {
        "one": {"url": str(tmp_path / "one"), "pipelines": ["acme/upstream"]},
        "two": {"url": str(second), "pipelines": ["acme/upstream"]},
    })
    report = snapshot.make(folder)
    assert report.stores == ["one", "two"]
    stores = Stores.configured()
    assert len(snapshot.readable_snapshots(stores)[0]) == 1
    assert len(FolderStore(second).all_snapshot_files()) == 1


def test_read_only_routing_fails_before_any_write(tmp_path, monkeypatch):
    folder = pipeline(tmp_path)
    first = tmp_path / "one"
    configure(tmp_path, monkeypatch, {
        "one": {"url": str(first), "pipelines": ["acme/upstream"]},
        "two": {"url": str(tmp_path / "two"), "read_only": True, "pipelines": ["acme/upstream"]},
    })
    with pytest.raises(ReadOnlyStoreError):
        snapshot.make(folder)
    assert not first.exists()


def test_catalog_migration_retains_backup_and_reports_unsnapshotted(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    original = '[project]\ntype="catalog"\nname="Mine"\n[pipelines."acme/upstream"]\npath="../upstream"\n'
    (home / "chartbook.toml").write_text(original)
    result = CliRunner().invoke(main, ["catalog", "migrate"])
    assert result.exit_code == 0, result.output
    assert "has no snapshot" in result.output
    assert (home / "chartbook.toml.pre-0.4.bak").read_text() == original
    assert (home / "catalog.toml").exists()
    assert not (home / "chartbook.toml").exists()


def test_move_copies_verifies_and_routes_before_source_disappears(tmp_path, monkeypatch):
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    source = FolderStore(tmp_path / "one")
    taken = snapshot.make(folder, source).snapshot
    destination = tmp_path / "two"
    destination.mkdir()
    path = configure(tmp_path, monkeypatch, {"one": {"url": str(source)}, "two": {"url": str(destination)}})
    stores = Stores.configured()
    count, size = move("acme/upstream", stores, "two", dry_run=True)
    assert count == 1 and size > 0 and taken.path.exists()
    count, _ = move("acme/upstream", stores, "two")
    assert count == 1
    assert not source.all_snapshot_files()
    target = FolderStore(destination)
    assert len(target.all_snapshot_files()) == 1
    assert not target.verify(taken.hashes())
    assert "acme/upstream" in Stores.configured().named("two").pipelines


def _files_under(folder):
    return sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file())


def test_move_leaves_no_files_of_the_pipeline_in_its_source(tmp_path):
    import os
    from chartbook.multi_store import NamedStore
    from chartbook.store import pipeline_folder
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    other = create_pipeline_project(tmp_path / "other", pipeline_id="acme/other")
    _git(other, "init", "--quiet", "-b", "main")
    _git(other, "add", "-A")
    _git(other, "commit", "--quiet", "-m", "Initial")
    (tmp_path / "two").mkdir()
    source, target = FolderStore(tmp_path / "one"), FolderStore(tmp_path / "two")
    # The second snapshot uses the files the first one's folder keeps
    first = snapshot.make(folder, source, made_at="2026-01-01T00:00:00Z").snapshot
    (folder / "README.md").write_text("Changed\n")
    _git(folder, "commit", "--quiet", "-am", "Change the README")
    second = snapshot.make(folder, source, made_at="2026-01-02T00:00:00Z").snapshot
    assert first.commit != second.commit
    kept = snapshot.make(other, source).snapshot
    # A sync service's copy beside another pipeline's files, an hour old: only gc removes it
    stray = Path(kept.path).parent.parent / "README (1).md"
    stray.write_text("copy")
    os.utime(stray, (0, 0))
    before = _files_under(source.root / "pipelines" / pipeline_folder("acme/other"))
    stores = Stores([NamedStore("one", str(source), source), NamedStore("two", str(target), target)])
    count, _ = move("acme/upstream", stores, "two")
    assert count == 2
    assert not _files_under(source.root / "pipelines" / pipeline_folder("acme/upstream"))
    assert _files_under(source.root / "pipelines" / pipeline_folder("acme/other")) == before
    assert not source.verify(kept.hashes())
    assert not target.verify(first.hashes() | second.hashes())


def test_move_that_cannot_remove_files_still_routes_and_says_what_moved(tmp_path, monkeypatch):
    from chartbook.store import StoreError, TidyError
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    source = FolderStore(tmp_path / "one")
    snapshot.make(folder, source)
    (tmp_path / "two").mkdir()
    configure(tmp_path, monkeypatch, {"one": {"url": str(source)}, "two": {"url": str(tmp_path / "two")}})

    def refuse(self, pipeline, dry_run=False):
        raise TidyError("Cannot remove one/pipelines/acme+upstream/x: Permission denied.", [], [("x", "Permission denied")])

    monkeypatch.setattr(FolderStore, "tidy_pipeline", refuse)
    with pytest.raises(StoreError, match="Moved 1 snapshot.*left behind.*Permission denied"):
        move("acme/upstream", Stores.configured(), "two")
    assert not source.all_snapshot_files()
    assert "acme/upstream" in Stores.configured().named("two").pipelines


def test_move_refuses_one_store_under_two_names(tmp_path):
    import os
    from chartbook.multi_store import NamedStore
    from chartbook.store import StoreError, pipeline_folder
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    source = FolderStore(tmp_path / "one")
    taken = snapshot.make(folder, source).snapshot
    try:
        os.symlink(tmp_path / "one", tmp_path / "alias")
    except OSError:
        pytest.skip("no symlinks here")
    alias = FolderStore(tmp_path / "alias")
    before = _files_under(source.root / "pipelines" / pipeline_folder("acme/upstream"))
    stores = Stores([NamedStore("one", str(source), source), NamedStore("two", str(alias), alias)])
    with pytest.raises(StoreError, match="one store under two names"):
        move("acme/upstream", stores, "two")
    assert _files_under(source.root / "pipelines" / pipeline_folder("acme/upstream")) == before
    assert not source.verify(taken.hashes())


def test_move_whose_source_cannot_be_tidied_still_routes(tmp_path, monkeypatch):
    from chartbook.store import MIGRATE_JOURNAL, StoreError, TMP_DIR
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    source = FolderStore(tmp_path / "one")
    snapshot.make(folder, source)
    (tmp_path / "two").mkdir()
    configure(tmp_path, monkeypatch, {"one": {"url": str(source)}, "two": {"url": str(tmp_path / "two")}})
    stores = Stores.configured()
    (source.root / TMP_DIR).mkdir(exist_ok=True)
    (source.root / TMP_DIR / MIGRATE_JOURNAL).write_text("")
    with pytest.raises(StoreError, match="Moved 1 snapshot.*left behind"):
        move("acme/upstream", stores, "two")
    assert "acme/upstream" in Stores.configured().named("two").pipelines
    assert FolderStore(tmp_path / "two").all_snapshot_files()


def test_move_with_keep_leaves_the_source_whole(tmp_path):
    from chartbook.multi_store import NamedStore
    from chartbook.store import pipeline_folder
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    (tmp_path / "two").mkdir()
    source, target = FolderStore(tmp_path / "one"), FolderStore(tmp_path / "two")
    taken = snapshot.make(folder, source).snapshot
    before = _files_under(source.root / "pipelines" / pipeline_folder("acme/upstream"))
    stores = Stores([NamedStore("one", str(source), source), NamedStore("two", str(target), target)])
    move("acme/upstream", stores, "two", keep=True)
    assert _files_under(source.root / "pipelines" / pipeline_folder("acme/upstream")) == before
    assert not source.verify(taken.hashes())


def test_pin_and_frozen_find_newest_in_second_store(tmp_path, monkeypatch):
    from chartbook import lock
    folder = pipeline(tmp_path)
    first, second = FolderStore(tmp_path / "one"), FolderStore(tmp_path / "two")
    snapshot.make(folder, first, made_at="2026-01-01T00:00:00Z")
    latest = snapshot.make(folder, second, made_at="2026-01-02T00:00:00Z").snapshot
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\n"acme/upstream"={}\n')
    configure(tmp_path, monkeypatch, {"one": {"url": str(first)}, "two": {"url": str(second)}})
    report = lock.pin(consumer, clone_missing=False)
    assert not report.problems
    assert report.snapshots["acme/upstream"].made_at == latest.made_at
    assert not lock.verify(consumer, note=True).problems
    assert first.roots() and second.roots()


def test_relative_store_is_relative_to_catalog_not_cwd(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, {"one": {"url": "../storage"}})
    monkeypatch.chdir(tmp_path.parent)
    assert Stores.configured().default().root == path.parent.parent / "storage"


def test_dependency_store_is_read_only_and_frozen_reads_it(tmp_path, monkeypatch):
    import boto3
    from moto import mock_aws
    from chartbook.stores.s3 import S3Store
    from chartbook import lock
    from chartbook.resolve import resolve
    import tomli
    folder = pipeline(tmp_path)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="chartbook-public-test")
        remote = S3Store("s3://chartbook-public-test/data", client=client)
        snapshot.make(folder, remote)
        before = {o["Key"] for o in client.list_objects_v2(Bucket="chartbook-public-test")["Contents"]}
        configure(tmp_path, monkeypatch, {"mine": {"url": str(tmp_path / "local")}})
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        (consumer / "chartbook.toml").write_text('[project]\nid="acme/consumer"\n[dependencies]\n"acme/upstream"={store="s3://chartbook-public-test/data"}\n')
        report = lock.pin(consumer, clone_missing=False)
        assert not report.problems
        assert not lock.verify(consumer, note=True).problems
        name = next(iter(tomli.loads((folder / "chartbook.toml").read_text())["dataframes"]))
        location = resolve(f"acme/upstream:{name}", start_dirs=[consumer])
        assert location.path.is_file()
        after = {o["Key"] for o in client.list_objects_v2(Bucket="chartbook-public-test")["Contents"]}
        assert before == after


def test_anonymous_s3_client_does_not_sign_requests(tmp_path):
    from chartbook.stores.s3 import S3Store
    from botocore import UNSIGNED
    store = S3Store("s3://public-chartbook/data?anonymous=true", cache=tmp_path)
    assert store._client.meta.config.signature_version == UNSIGNED


def test_move_between_folder_and_s3_preserves_files_and_retention_notes(tmp_path):
    import boto3
    from moto import mock_aws
    from chartbook.multi_store import NamedStore
    from chartbook.stores.s3 import S3Store
    from chartbook.transfer import move
    folder = pipeline(tmp_path)
    local = FolderStore(tmp_path / "local")
    taken = snapshot.make(folder, local).snapshot
    lockfile = tmp_path / "consumer/chartbook.lock"
    local.add_root(lockfile, taken.hashes(), [(taken.commit, taken.made_at)], machine="colleague")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="chartbook-move-test")
        remote = S3Store("s3://chartbook-move-test/data", client=client)
        stores = Stores([NamedStore("local", str(local), local), NamedStore("remote", str(remote), remote)])
        move("acme/upstream", stores, "remote")
        assert not local.all_snapshot_files()
        assert not _files_under(local.root / "pipelines" / "acme+upstream")
        assert remote.all_snapshot_files()
        assert not remote.verify(taken.hashes())
        root = remote.root_of(lockfile, "colleague")
        assert root is not None and set(root.hashes) == taken.hashes()
        move("acme/upstream", stores, "local")
        assert not remote.all_snapshot_files()
        left = client.list_objects_v2(Bucket="chartbook-move-test", Prefix="data/pipelines/acme+upstream/")
        assert not left.get("Contents")
        assert local.all_snapshot_files()
        assert not local.verify(taken.hashes())


def test_migration_keeps_disabled_aliases_under_the_pipeline_identity(tmp_path, monkeypatch):
    import tomli
    from chartbook.catalog_config import migrate
    folder = pipeline(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    legacy = home / "chartbook.toml"
    legacy.write_text(tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"disabled": ["old-alias"], "old-alias": {"path": "../upstream"}}}))
    path, missing = migrate()
    doc = tomli.loads(path.read_text())
    assert doc["pipelines"] == {"acme/upstream": {"disabled": True}}
    assert missing == []
    assert (home / "chartbook.toml.pre-0.4.bak").exists()


def test_maintenance_unknown_selection_is_an_actionable_error(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, {"mine": {"url": str(tmp_path / "store")}})
    for command in ("verify", "gc", "info"):
        result = CliRunner().invoke(main, ["store", command, "--store", "typo"])
        assert result.exit_code != 0
        assert "Unknown store 'typo'; choose mine" in result.output


def test_an_unavailable_remote_does_not_hide_a_second_copy(tmp_path):
    from chartbook.multi_store import NamedStore
    folder = pipeline(tmp_path)
    good = FolderStore(tmp_path / "good")
    taken = snapshot.make(folder, good).snapshot
    class Offline:
        def all_snapshot_files(self):
            raise StoreUnreachableError("Disconnected")
        def has(self, key):
            raise StoreUnreachableError("Disconnected")
    stores = Stores([NamedStore("offline", "plugin://offline", Offline()), NamedStore("good", str(good), good)])
    with pytest.warns(UserWarning, match="offline.*unreachable") as messages:
        assert stores.snapshots()[0].commit == taken.commit
        assert stores.get(next(iter(taken.hashes()))).exists()
        stores.snapshots()
    assert len(messages) == 1


def test_migration_follows_a_configured_catalog_and_updates_its_path(tmp_path, monkeypatch):
    from chartbook.catalog_config import migrate
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    custom = tmp_path / "team"
    custom.mkdir()
    old = custom / "chartbook.toml"
    old.write_text('[project]\ntype="catalog"\nname="Team"\n[pipelines]\n')
    config.write_global_settings({"catalog": {"path": str(old)}})
    target, _ = migrate()
    assert target == custom / "catalog.toml"
    assert config.get_default_catalog_path() == target
    assert old.with_suffix(".toml.pre-0.4.bak").exists()


@pytest.mark.parametrize("origin", ["user", "system"])
def test_catalog_migration_explains_how_to_retire_old_store_settings(tmp_path, monkeypatch, origin):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    monkeypatch.delenv("CHARTBOOK_STORE", raising=False)
    settings = home / "settings.toml" if origin == "user" else tmp_path / "system-settings.toml"
    if origin == "system":
        monkeypatch.setenv("CHARTBOOK_SYSTEM_SETTINGS", str(settings))
    original_settings = tomli_w.dumps({"store": {"url": str(tmp_path / "store")}})
    settings.write_text(original_settings)
    (home / "chartbook.toml").write_text('[project]\ntype="catalog"\n[pipelines]\n')
    result = CliRunner().invoke(main, ["catalog", "migrate"])
    assert result.exit_code == 0, result.output
    assert "Remove the obsolete [store] table" in result.output
    assert str(settings) in result.output
    assert "fallback for other catalogs" in result.output
    assert settings.read_text() == original_settings
