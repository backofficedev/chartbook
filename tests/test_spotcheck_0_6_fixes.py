"""Regression tests for 0.6.0 spot-check fixes."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from chartbook import built, config, lock, sharing, snapshot, transfer
from chartbook.cli import main
from chartbook.multi_store import NamedStore, Stores
from chartbook.store import (
    FolderStore,
    PathTooLongError,
    _root_path,
    root_document,
    root_name,
    this_machine,
)


def _git(folder: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=folder,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


def _make_pipeline(root: Path, pid: str = "acme/demo", files: dict[str, bytes] | None = None, manifest: str | None = None) -> Path:
    folder = root / pid.replace("/", "_")
    folder.mkdir(parents=True, exist_ok=True)
    if manifest is None:
        manifest = (
            f'[project]\nid = "{pid}"\n\n'
            '[files.data]\npath = "data.bin"\n'
        )
    (folder / "chartbook.toml").write_text(manifest, encoding="utf-8")
    for rel, content in (files or {"data.bin": b"v1" * 100}).items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(folder, "init", "-b", "main")
    _git(folder, "add", ".")
    _git(folder, "commit", "-m", "initial")
    return folder


def _configure_catalog(tmp_path: Path, monkeypatch, stores: dict[str, dict]) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir(exist_ok=True)
    catalog = catalog_dir / "catalog.toml"
    lines = ['[catalog]\nname = "Test"\n']
    for name, opts in stores.items():
        lines.append(f"\n[stores.{name}]\n")
        for key, value in opts.items():
            lines.append(f"{key} = {json.dumps(value)}\n")
    catalog.write_text("".join(lines), encoding="utf-8")
    config.write_global_settings({"catalog": {"path": str(catalog)}})
    return catalog


# ---------------------------------------------------------------------------
# 1. Overlapping assets in copied increments
# ---------------------------------------------------------------------------


def test_copy_increment_with_overlapping_assets_preserves_kept_in(tmp_path):
    """When two assets share a file that an increment keeps in builds_on, copying the increment preserves kept_in for both."""
    manifest = (
        '[project]\nid = "acme/overlap"\n\n'
        '[files.one_file]\npath = "out/shared.txt"\n\n'
        '[files.whole_dir]\npath = "out"\n'
    )
    pipeline = _make_pipeline(
        tmp_path,
        pid="acme/overlap",
        files={"out/shared.txt": b"unchanged" * 500, "out/changing.txt": b"v1"},
        manifest=manifest,
    )
    src = FolderStore(tmp_path / "src")
    dst = FolderStore(tmp_path / "dst")

    first = snapshot.make(pipeline, store=src, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    (pipeline / "out/changing.txt").write_bytes(b"v2-updated")
    _git(pipeline, "add", ".")
    _git(pipeline, "commit", "-m", "update changing")
    second = snapshot.make(pipeline, store=src, complete=False, made_at="2026-01-02T00:00:00Z").snapshot

    # Confirm second is an increment on first in src
    assert src.builds_on(second.path) is not None

    # Copy both snapshots via transfer.copy_snapshot (used by store move) and sharing.copy_snapshots (export/import)
    whole: set[str] = set()
    first_dst = transfer.copy_snapshot(first, src, dst, whole=whole)
    second_dst = transfer.copy_snapshot(second, src, dst, whole=whole)

    # Every asset in the copied increment verifies whole and is readable
    problems = dst.verify(sorted(second.hashes()), "acme/overlap")
    assert problems == []
    for asset_hash in second.hashes():
        kept = dst.files(asset_hash, "acme/overlap", snapshot=(second.commit, second.made_at))
        assert all(f.location.is_file() for f in kept.files)

    # Inspect the written record: both assets reference first's folder for out/shared.txt
    doc = json.loads(second_dst.read_text(encoding="utf-8"))
    first_folder_name = first_dst.parent.parent.name
    shared_entries = [
        f
        for rec in doc["records"]
        for f in rec["stored"]["files"]
        if f["path"] == "out/shared.txt"
    ]
    assert len(shared_entries) == 2
    assert all(entry["kept_in"] == first_folder_name for entry in shared_entries)

    # Also verify sharing.copy_snapshots (export/import)
    dst2 = FolderStore(tmp_path / "dst2")
    sharing.copy_snapshots(src.records(), dst2)
    assert dst2.verify(sorted(second.hashes()), "acme/overlap") == []


# ---------------------------------------------------------------------------
# 2. Foreign OS root paths and host/node preservation across store move
# ---------------------------------------------------------------------------


def test_root_path_preserves_foreign_os_paths_verbatim(monkeypatch):
    win_drive = r"C:\Users\ra\repo\chartbook.lock"
    win_unc = r"\\server\share\repo\chartbook.lock"
    posix_path = "/Users/mac/repo/chartbook.lock"

    monkeypatch.setattr(os, "name", "posix")
    assert _root_path(win_drive) == win_drive
    assert _root_path(win_unc) == win_unc
    assert root_document(win_drive, [], machine="m1", host="WIN-PC", node="aabbccddeeff")["lockfile"] == win_drive
    assert root_document(win_drive, [], machine="m1", host="WIN-PC", node="aabbccddeeff")["host"] == "WIN-PC"
    assert root_document(win_drive, [], machine="m1", host="WIN-PC", node="aabbccddeeff")["node"] == "aabbccddeeff"

    monkeypatch.setattr(os, "name", "nt")
    assert _root_path(posix_path) == posix_path


def test_store_move_preserves_windows_root_paths_and_host_node(tmp_path, monkeypatch):
    pipeline = _make_pipeline(tmp_path, pid="acme/winroot")
    src = FolderStore(tmp_path / "src")
    (tmp_path / "dst").mkdir()
    dst = FolderStore(tmp_path / "dst")
    taken = snapshot.make(pipeline, store=src, complete=True, made_at="2026-01-01T00:00:00Z").snapshot

    win_lock = r"C:\Users\colleague\projects\study\chartbook.lock"
    win_machine = "win-machine-id-123"
    win_host = "COLLEAGUE-DESKTOP"
    win_node = "112233445566"
    src.add_root(
        win_lock,
        taken.hashes(),
        [("acme/winroot", taken.commit, taken.made_at)],
        machine=win_machine,
        host=win_host,
        node=win_node,
    )
    (src_root,) = src.roots()
    assert src_root.written == win_lock
    assert src_root.host == win_host
    assert src_root.node == win_node

    stores = Stores([
        NamedStore("src", str(src.root), src),
        NamedStore("dst", str(dst.root), dst),
    ])
    transfer.move("acme/winroot", stores, "dst", keep=True, route=False)

    (dst_root,) = dst.roots()
    assert dst_root.note == src_root.note
    assert dst_root.written == win_lock
    assert dst_root.machine == win_machine
    assert dst_root.host == win_host
    assert dst_root.node == win_node
    assert dst.root_of(win_lock, win_machine) is not None

    # Moving again merges into the same note rather than creating a second mangled note
    transfer.move("acme/winroot", stores, "dst", keep=True, route=False)
    assert len(dst.roots()) == 1


# ---------------------------------------------------------------------------
# 3. One-pipeline GC reminder reports accurate freed bytes
# ---------------------------------------------------------------------------


def test_narrow_to_pipeline_counts_pipeline_owned_deleted_objects(tmp_path):
    store = FolderStore(tmp_path / "store")
    alpha = _make_pipeline(tmp_path, pid="acme/alpha", files={"data.bin": b"A" * 50_000})
    beta = _make_pipeline(tmp_path, pid="acme/beta", files={"data.bin": b"B" * 30_000})

    snapshot.make(alpha, store=store, complete=True, made_at="2026-01-01T00:00:00Z")
    (alpha / "data.bin").write_bytes(b"A2" * 25_000)
    _git(alpha, "add", ".")
    _git(alpha, "commit", "-m", "v2")
    snapshot.make(alpha, store=store, complete=True, made_at="2026-02-01T00:00:00Z")

    snapshot.make(beta, store=store, complete=True, made_at="2026-01-01T00:00:00Z")
    (beta / "data.bin").write_bytes(b"B2" * 15_000)
    _git(beta, "add", ".")
    _git(beta, "commit", "-m", "v2")
    snapshot.make(beta, store=store, complete=True, made_at="2026-02-01T00:00:00Z")

    plan_alpha = lock.plan_gc(store, keep_days=0, recent_seconds=0, looks=False, pipeline="acme/alpha")
    plan_beta = lock.plan_gc(store, keep_days=0, recent_seconds=0, looks=False, pipeline="acme/beta")
    plan_all = lock.plan_gc(store, keep_days=0, recent_seconds=0, looks=False)

    assert len(plan_alpha.snapshots_delete) == 1
    assert plan_alpha.size_bytes >= 50_000
    assert plan_alpha.size_bytes < plan_all.size_bytes
    assert len(plan_beta.snapshots_delete) == 1
    assert plan_beta.size_bytes >= 30_000
    assert plan_alpha.size_bytes + plan_beta.size_bytes == plan_all.size_bytes

    # A pipeline with nothing removable reports 0 bytes and empty delete
    gamma = _make_pipeline(tmp_path, pid="acme/gamma", files={"data.bin": b"G" * 10_000})
    snapshot.make(gamma, store=store, complete=True, made_at="2026-02-01T00:00:00Z")
    plan_gamma = lock.plan_gc(store, keep_days=0, recent_seconds=0, looks=False, pipeline="acme/gamma")
    assert plan_gamma.snapshots_delete == []
    assert plan_gamma.delete == []
    assert plan_gamma.size_bytes == 0


# ---------------------------------------------------------------------------
# 4. store gc --forget-note: 0.5 layout safety, prefix stripping, multi-store
# ---------------------------------------------------------------------------


def test_forget_note_refuses_0_5_store_without_deleting_note(tmp_path, monkeypatch):
    store_root = tmp_path / "old_store"
    store_root.mkdir()
    (store_root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8")
    (store_root / "roots").mkdir()
    lockfile = tmp_path / "proj" / "chartbook.lock"
    machine = this_machine()
    note_file = store_root / "roots" / root_name(lockfile, machine)
    note_file.write_text(json.dumps(root_document(lockfile, [], [], machine)) + "\n", encoding="utf-8")

    monkeypatch.setenv(config.STORE_ENV_VAR, str(store_root))
    result = CliRunner().invoke(main, ["store", "gc", "--forget-note", note_file.name, "--dry-run"])
    assert result.exit_code == 1
    assert note_file.exists(), "0.5 store note must not be deleted before layout check"


def test_forget_note_accepts_roots_prefix_and_works_in_multistore(tmp_path, monkeypatch):
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1")
    taken = snapshot.make(p1, store=s2, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    _configure_catalog(tmp_path, monkeypatch, {"one": {"url": str(s1.root)}, "two": {"url": str(s2.root)}})

    lockfile = tmp_path / "proj" / "chartbook.lock"
    machine = this_machine()
    s2.add_root(lockfile, taken.hashes(), [("acme/p1", taken.commit, taken.made_at)], machine=machine)
    (note,) = s2.roots()

    # Accepts the `_chartbook/roots/<name>` form that `store gc` prints. A dry run leaves the note,
    # and still plans every store, not only the one that holds it.
    result = CliRunner().invoke(main, ["store", "gc", "--forget-note", f"_chartbook/roots/{note.note}", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Would forget note" in result.output
    assert "Forgot note" not in result.output
    assert "Store one:" in result.output and "Store two:" in result.output
    assert len(s2.roots()) == 1

    # A real run forgets the note in the store that has it, and still plans the other
    real = CliRunner().invoke(main, ["store", "gc", "--forget-note", f"_chartbook/roots/{note.note}"])
    assert real.exit_code == 0, real.output
    assert "Forgot note" in real.output
    assert "Store one:" in real.output and "Store two:" in real.output
    assert s2.roots() == []

    # When the same note filename exists in BOTH stores, refuse to guess without --store
    s1.add_root(lockfile, taken.hashes(), [("acme/p1", taken.commit, taken.made_at)], machine=machine)
    s2.add_root(lockfile, taken.hashes(), [("acme/p1", taken.commit, taken.made_at)], machine=machine)
    ambiguous = CliRunner().invoke(main, ["store", "gc", "--forget-note", note.note, "--dry-run"])
    assert ambiguous.exit_code != 0
    assert "select one with --store NAME" in ambiguous.output
    assert len(s1.roots()) == 1 and len(s2.roots()) == 1


def test_forget_note_names_a_store_that_could_not_be_read(tmp_path, monkeypatch):
    s1 = FolderStore(tmp_path / "s1")
    _configure_catalog(tmp_path, monkeypatch, {"one": {"url": str(s1.root)}, "away": {"url": str(tmp_path / "away")}})
    result = CliRunner().invoke(main, ["store", "gc", "--forget-note", "a" * 32 + ".json", "--dry-run"])
    assert result.exit_code != 0
    assert "away" in result.output and "could not be read" in result.output
    assert s1.roots() == []


# ---------------------------------------------------------------------------
# 5. Multi-store verify and gc continue across all stores after store 1 fails
# ---------------------------------------------------------------------------


def test_multistore_verify_and_gc_check_remaining_stores_after_failure(tmp_path, monkeypatch):
    broken = FolderStore(tmp_path / "broken")
    healthy = FolderStore(tmp_path / "healthy")
    p1 = _make_pipeline(tmp_path, pid="acme/p1")
    p2 = _make_pipeline(tmp_path, pid="acme/p2")
    t1 = snapshot.make(p1, store=broken, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    snapshot.make(p2, store=healthy, complete=True, made_at="2026-01-01T00:00:00Z")
    _configure_catalog(tmp_path, monkeypatch, {"broken": {"url": str(broken.root)}, "healthy": {"url": str(healthy.root)}})

    # Break a file in `broken` so `store verify` fails there
    broken_file = t1.path.parent.parent / "data.bin"
    broken_file.unlink()
    verify_res = CliRunner().invoke(main, ["store", "verify"])
    assert verify_res.exit_code != 0
    assert "Store broken:" in verify_res.output
    assert "Store healthy:" in verify_res.output
    assert "Maintenance failed in stores: broken" in verify_res.output

    # Put an unreadable note in `broken` so `store gc` fails there
    roots_dir = broken.roots_path()
    roots_dir.mkdir(parents=True, exist_ok=True)
    (roots_dir / ("a" * 32 + ".json")).write_text("{not-json", encoding="utf-8")
    gc_res = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
    assert gc_res.exit_code != 0
    assert "Store broken:" in gc_res.output
    assert "Store healthy:" in gc_res.output
    assert "Maintenance failed in stores: broken" in gc_res.output


# ---------------------------------------------------------------------------
# 6. Stores.root_of merges disjoint notes and prevents dropping pins
# ---------------------------------------------------------------------------


def test_stores_root_of_merges_disjoint_notes_and_note_this_machine_converges(tmp_path):
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"one"})
    p2 = _make_pipeline(tmp_path, pid="acme/p2", files={"data.bin": b"two"})
    t1 = snapshot.make(p1, store=s1, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    t2 = snapshot.make(p2, store=s2, complete=True, made_at="2026-01-01T00:00:00Z").snapshot

    stores = Stores([NamedStore("one", str(s1.root), s1), NamedStore("two", str(s2.root), s2)])
    lockfile = tmp_path / "consumer" / "chartbook.lock"
    lockfile.parent.mkdir()
    machine = this_machine()

    h1 = next(iter(t1.hashes()))
    h2 = next(iter(t2.hashes()))
    s1.add_root(lockfile, [h1], [("acme/p1", t1.commit, t1.made_at)], machine=machine)
    s2.add_root(lockfile, [h2], [("acme/p2", t2.commit, t2.made_at)], machine=machine)

    merged = stores.root_of(lockfile, machine=machine)
    assert merged is not None
    assert set(merged.hashes) == {h1, h2}
    assert set(merged.snapshots) == {("acme/p1", t1.commit, t1.made_at), ("acme/p2", t2.commit, t2.made_at)}

    # A partial git failure (pins.complete = False) must NOT drop h2 from s2
    partial = lock.NotePins(hashes={h1}, snapshots={("acme/p1", t1.commit, t1.made_at)}, labelled=set(), complete=False)
    with patch.object(lock, "pins_for_note", return_value=partial):
        lock.write_note(lockfile, lock.Lock(lockfile, []), stores, machine=machine)
    assert {h1, h2}.issubset(set(s1.root_of(lockfile, machine).hashes))
    assert {h1, h2}.issubset(set(s2.root_of(lockfile, machine).hashes))

    # Once both stores match, note_this_machine does not rewrite needlessly
    complete = lock.NotePins(
        hashes={h1, h2},
        snapshots={("acme/p1", t1.commit, t1.made_at), ("acme/p2", t2.commit, t2.made_at)},
        labelled=set(),
        complete=True,
    )
    with patch.object(lock, "pins_for_note", return_value=complete):
        wrote, err = lock.note_this_machine(lockfile, lock.Lock(lockfile, []), stores)
    assert (wrote, err) == (False, "")


# ---------------------------------------------------------------------------
# 7. Smaller edge cases
# ---------------------------------------------------------------------------


def test_copy_snapshot_by_rule_falls_back_to_complete_on_path_too_long(tmp_path):
    pipeline = _make_pipeline(tmp_path, pid="acme/long")
    src = FolderStore(tmp_path / "src")
    dst = FolderStore(tmp_path / "dst")
    first = snapshot.make(pipeline, store=src, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    (pipeline / "data.bin").write_bytes(b"v2")
    _git(pipeline, "add", ".")
    _git(pipeline, "commit", "-m", "v2")
    second = snapshot.make(pipeline, store=src, complete=False, made_at="2026-01-02T00:00:00Z").snapshot

    whole: set[str] = set()
    transfer.copy_snapshot(first, src, dst, whole=whole)

    from chartbook.store import _FolderPending

    real_write = _FolderPending.write
    calls = {"n": 0}

    def fail_increment_once(self, document):
        calls["n"] += 1
        if calls["n"] == 1 and self.builds_on is not None:
            raise PathTooLongError("too long under increments/")
        return real_write(self, document)

    with patch.object(_FolderPending, "write", fail_increment_once):
        copied = transfer.copy_snapshot(second, src, dst, decides=True, whole=whole)

    assert calls["n"] == 2
    assert dst.builds_on(copied) is None
    assert dst.verify(sorted(second.hashes()), "acme/long") == []


def test_built_check_raises_not_held_when_git_source_listing_fails(tmp_path):
    manifest = (
        '[project]\nid = "acme/built"\n\n'
        '[scripts]\nbuild = "echo hi"\n\n'
        '[files.out]\npath = "out.txt"\n'
    )
    pipeline = _make_pipeline(tmp_path, pid="acme/built", files={"out.txt": b"built"}, manifest=manifest)
    note = {
        "schema": built.SCHEMA,
        "state": "built",
        "token": "t",
        "folder": str(pipeline),
        "pipeline": "acme/built",
        "machine": built._machine(),
        "began_at": "2026-01-01T00:00:00Z",
        "built_at": "2026-01-01T00:00:01Z",
        "hashed_at": 1_700_000_000,
        "source": {"chartbook.toml": {"hash": "sha256:" + "0" * 64, "size": 1, "time": 1}},
        "outputs": {},
    }
    with patch.object(built, "source_files", return_value=None):
        with pytest.raises(built.NotHeld) as exc_info:
            built.held(pipeline, note)
    assert exc_info.value.why == "unreadable"


def test_store_ls_formats_single_store_layout_error_cleanly(tmp_path, monkeypatch):
    store_root = tmp_path / "mixed"
    store_root.mkdir()
    (store_root / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8")
    (store_root / "pipelines").mkdir()
    monkeypatch.setenv(config.STORE_ENV_VAR, str(store_root))

    result = CliRunner().invoke(main, ["store", "ls"])
    assert result.exit_code == 1
    assert "Store : " not in result.output
    assert "unreachable" not in result.output
    assert "not read" in result.output


def test_store_ls_exits_when_one_store_cannot_be_read(tmp_path, monkeypatch):
    healthy = FolderStore(tmp_path / "healthy")
    pipeline = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"1" * 100})
    snapshot.make(pipeline, store=healthy, complete=True, made_at="2026-01-01T00:00:00Z")
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8")
    (mixed / "pipelines").mkdir()
    _configure_catalog(tmp_path, monkeypatch, {"healthy": {"url": str(healthy.root)}, "mixed": {"url": str(mixed)}})

    result = CliRunner().invoke(main, ["store", "ls"])
    assert result.exit_code == 1, result.output
    assert "not read" in result.output
    assert "acme/p1" in result.output


def test_store_info_multistore_includes_store_flag_in_gc_hint(tmp_path, monkeypatch):
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"1" * 1000})
    snapshot.make(p1, store=s1, complete=True, made_at="2020-01-01T00:00:00Z")
    (p1 / "data.bin").write_bytes(b"2" * 1000)
    _git(p1, "add", ".")
    _git(p1, "commit", "-m", "v2")
    snapshot.make(p1, store=s1, complete=True, made_at="2026-01-01T00:00:00Z")

    _configure_catalog(tmp_path, monkeypatch, {"one": {"url": str(s1.root)}, "two": {"url": str(s2.root)}})
    result = CliRunner().invoke(main, ["store", "info"])
    assert result.exit_code == 0, result.output
    assert "`chartbook store gc --store one` would clear" in result.output


def _omit_snapshot_list(store: FolderStore, lockfile: Path, machine: str) -> None:
    """Rewrite a note as one from before notes recorded snapshots: no snapshot list."""
    root = store.root_of(lockfile, machine=machine)
    path = store.roots_path() / root.note
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("snapshots", None)
    document.pop("newest", None)
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    assert store.root_of(lockfile, machine=machine).snapshots is None


def _lock_pinning(folder: Path, dependency: str, taken, content_hash: str) -> Path:
    locked = lock.Lock(root=folder.name)
    locked.dependencies = [{
        "id": dependency,
        "via": "store",
        "location": {
            "kind": "store",
            "pipeline": dependency,
            "commit": taken.commit,
            "first_commit": taken.commit,
        },
        "snapshot": taken.made_at,
    }]
    locked.assets = {
        f"{dependency}:data": {
            "id": f"{dependency}:data",
            "kind": "Dataframe",
            "pipeline": dependency,
            "content_hash": content_hash,
        }
    }
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / lock.LOCK_FILE
    lock.write_lock(locked, path)
    return path


def test_partial_read_keeps_newest_holder_of_an_old_note(tmp_path):
    """A note with no snapshot list keeps the newest snapshot of each object. A partial git answer must not replace that with only the snapshots it saw."""
    store = FolderStore(tmp_path / "store")
    pipeline = _make_pipeline(tmp_path, pid="acme/aged", files={"data.bin": b"old" * 40})
    old = snapshot.make(pipeline, store=store, complete=True, made_at="2020-01-01T00:00:00Z").snapshot
    (pipeline / "data.bin").write_bytes(b"new" * 40)
    _git(pipeline, "add", ".")
    _git(pipeline, "commit", "-m", "v2")
    new = snapshot.make(pipeline, store=store, complete=True, made_at="2020-06-01T00:00:00Z").snapshot
    h_old = old.assets["file/data"]["content_hash"]
    h_new = new.assets["file/data"]["content_hash"]
    assert h_old != h_new

    machine = this_machine()
    lockfile = _lock_pinning(tmp_path / "consumer", "acme/aged", new, h_new)
    store.add_root(lockfile, [h_old], machine=machine)
    _omit_snapshot_list(store, lockfile, machine)

    partial = lock.NotePins(
        hashes={h_new},
        snapshots={("acme/aged", new.commit, new.made_at)},
        labelled=set(),
        complete=False,
    )
    with patch.object(lock, "pins_for_note", return_value=partial):
        wrote, err = lock.note_this_machine(lockfile, lock.Lock(lockfile, []), store)
    assert (wrote, err) == (True, "")
    noted = store.root_of(lockfile, machine=machine)
    assert noted.keeps_newest()
    assert h_old in noted.hashes and h_new in noted.hashes
    assert ("acme/aged", new.commit, new.made_at) in set(noted.snapshots)

    plan = lock.plan_gc(store, recent_seconds=0, keep_days=0, aggressive=True)
    kept = {(taken.commit, taken.made_at) for taken, _ in plan.snapshots_kept}
    assert (old.commit, old.made_at) in kept

    with patch.object(lock, "pins_for_note", return_value=partial):
        again, err = lock.note_this_machine(lockfile, lock.Lock(lockfile, []), store)
    assert (again, err) == (False, "")
    assert store.root_of(lockfile, machine=machine).keeps_newest()


def test_partial_read_keeps_newest_on_the_store_that_had_it(tmp_path):
    """Across stores, a note with no snapshot list keeps that rule, and a note that listed snapshots keeps its list."""
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"one"})
    p2 = _make_pipeline(tmp_path, pid="acme/p2", files={"data.bin": b"two"})
    t1 = snapshot.make(p1, store=s1, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    t2 = snapshot.make(p2, store=s2, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    machine = this_machine()
    lockfile = tmp_path / "consumer" / "chartbook.lock"
    lockfile.parent.mkdir()
    h1 = next(iter(t1.hashes()))
    h2 = next(iter(t2.hashes()))
    s1.add_root(lockfile, [h1], machine=machine)
    _omit_snapshot_list(s1, lockfile, machine)
    s2.add_root(lockfile, [h2], [("acme/p2", t2.commit, t2.made_at)], machine=machine)

    stores = Stores([NamedStore("one", str(s1.root), s1), NamedStore("two", str(s2.root), s2)])
    merged = stores.root_of(lockfile, machine=machine)
    assert merged.keeps_newest()
    assert ("acme/p2", t2.commit, t2.made_at) in set(merged.snapshots)

    partial = lock.NotePins(
        hashes={h1}, snapshots={("acme/p1", t1.commit, t1.made_at)}, labelled=set(), complete=False,
    )
    with patch.object(lock, "pins_for_note", return_value=partial):
        lock.write_note(lockfile, lock.Lock(lockfile, []), stores, machine=machine)

    left = s1.root_of(lockfile, machine=machine)
    right = s2.root_of(lockfile, machine=machine)
    assert left.keeps_newest() and {h1, h2} <= set(left.hashes)
    assert ("acme/p2", t2.commit, t2.made_at) in set(left.snapshots)
    assert not right.keeps_newest()
    assert {("acme/p1", t1.commit, t1.made_at), ("acme/p2", t2.commit, t2.made_at)} <= set(right.snapshots)
    assert {h1, h2} <= set(right.hashes)


def test_move_preserves_a_note_that_names_no_snapshots(tmp_path):
    pipeline = _make_pipeline(tmp_path, pid="acme/moved")
    src = FolderStore(tmp_path / "src")
    (tmp_path / "dst").mkdir()
    dst = FolderStore(tmp_path / "dst")
    taken = snapshot.make(pipeline, store=src, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    machine = this_machine()
    lockfile = tmp_path / "consumer" / "chartbook.lock"
    lockfile.parent.mkdir()
    src.add_root(lockfile, list(taken.hashes()), machine=machine)
    _omit_snapshot_list(src, lockfile, machine)
    pin = ("acme/moved", taken.commit, taken.made_at)
    dst.add_root(lockfile, ["sha256:" + "ab" * 32], [pin], machine=machine)

    stores = Stores([
        NamedStore("src", str(src.root), src),
        NamedStore("dst", str(dst.root), dst),
    ])
    transfer.move("acme/moved", stores, "dst", keep=True, route=False)
    moved = dst.root_of(lockfile, machine=machine)
    assert moved.keeps_newest()
    assert pin in set(moved.snapshots)
    assert set(taken.hashes()) <= set(moved.hashes)
