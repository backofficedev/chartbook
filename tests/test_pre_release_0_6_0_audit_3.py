"""Regression tests for the third pre-release 0.6.0 bug audit."""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_git_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")


def _commit_all(path: Path, message: str = "commit") -> str:
    _git(path, "add", "-A")
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# 1. lock.py: failed `pin --update` after relocating a dependency must not
#    corrupt chartbook.lock with the new location + old hashes
# ---------------------------------------------------------------------------


def test_failed_pin_update_after_relocate_keeps_old_location(tmp_path, monkeypatch):
    from chartbook import lock, snapshot
    from chartbook.store import FolderStore

    store_dir = tmp_path / "store"
    store = FolderStore(store_dir)
    monkeypatch.setenv("CHARTBOOK_STORE", str(store_dir))

    # Dependency A: has a snapshot
    dep_a = tmp_path / "dep_a"
    dep_a.mkdir()
    _init_git_repo(dep_a)
    (dep_a / "_data").mkdir()
    (dep_a / "_data" / "x.csv").write_text("k,v\n1,10\n", encoding="utf-8")
    (dep_a / "chartbook.toml").write_text(
        '[project]\nid = "acme/dep_a"\ntitle = "A"\nauthor = "T"\ncopyright = "2026"\n'
        '[dataframes.x]\nname = "x"\npath = "_data/x.csv"\n',
        encoding="utf-8",
    )
    commit_a = _commit_all(dep_a, "init a")
    snapshot.make(dep_a, store=store, complete=True)

    # Dependency B: git repo, NO snapshot
    dep_b = tmp_path / "dep_b"
    dep_b.mkdir()
    _init_git_repo(dep_b)
    (dep_b / "_data").mkdir()
    (dep_b / "_data" / "x.csv").write_text("k,v\n1,99\n", encoding="utf-8")
    (dep_b / "chartbook.toml").write_text(
        '[project]\nid = "acme/dep_b"\ntitle = "B"\nauthor = "T"\ncopyright = "2026"\n'
        '[dataframes.x]\nname = "x"\npath = "_data/x.csv"\n',
        encoding="utf-8",
    )
    _commit_all(dep_b, "init b")

    # Consumer pins dep_a
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    manifest_text = (
        '[project]\nid = "acme/consumer"\ntitle = "C"\nauthor = "T"\ncopyright = "2026"\n'
        '[dependencies]\ndep = { path = "../dep_a" }\n'
    )
    (consumer / "chartbook.toml").write_text(manifest_text, encoding="utf-8")
    lock.pin(consumer, store=store)

    locked_before = lock.read_lock(consumer)
    assert locked_before is not None
    dep_before = next(d for d in locked_before.dependencies if d["id"] == "dep")
    assert dep_before["location"]["path"] == "../dep_a"
    assert dep_before["location"]["commit"] == commit_a

    # Relocate to dep_b (which has no snapshot) and run pin --update
    (consumer / "chartbook.toml").write_text(
        manifest_text.replace("../dep_a", "../dep_b"),
        encoding="utf-8",
    )
    lock.update(consumer, store=store)

    # Lockfile must still record ../dep_a, not ../dep_b with dep_a's commit/hashes
    locked_after = lock.read_lock(consumer)
    assert locked_after is not None
    dep_after = next(d for d in locked_after.dependencies if d["id"] == "dep")
    assert dep_after["location"]["path"] == "../dep_a"
    assert dep_after["location"]["commit"] == commit_a

    # verify() must notice the relocation rather than silently passing
    report = lock.verify(consumer, store=store)
    assert report.problems


# ---------------------------------------------------------------------------
# 2. resolve.py: broken catalog.toml must not crash with UnboundLocalError
# ---------------------------------------------------------------------------


def test_resolve_broken_catalog_does_not_raise_unbound_local(tmp_path, monkeypatch):
    from chartbook import resolve as resolve_mod

    bad_catalog = tmp_path / "catalog.toml"
    bad_catalog.write_text("this is [ not valid toml !!!\n", encoding="utf-8")
    monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "store"))

    with pytest.raises(Exception) as exc_info:
        resolve_mod.resolve("yields", pipeline="acme/rates", catalog_path=bad_catalog)
    assert not isinstance(exc_info.value, UnboundLocalError)


# ---------------------------------------------------------------------------
# 3. lock.py: missing chartbook.toml raises LockError even without CHARTBOOK_STORE
# ---------------------------------------------------------------------------


def test_lock_pin_and_verify_missing_manifest_raise_lock_error(tmp_path, monkeypatch):
    from chartbook import lock

    monkeypatch.delenv("CHARTBOOK_STORE", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(lock.LockError):
        lock.pin(empty)
    with pytest.raises(lock.LockError):
        lock.verify(empty)


# ---------------------------------------------------------------------------
# 4. sharing.py: copy_snapshots handles _builds_on_there raising without
#    UnboundLocalError or size_bytes rollback
# ---------------------------------------------------------------------------


def test_sharing_copy_snapshots_builds_on_error_no_unbound_local(tmp_path):
    from chartbook import sharing
    from chartbook.store import FolderStore, StoreError

    src = FolderStore(tmp_path / "src_store")
    dst = FolderStore(tmp_path / "dst_store")

    pending = src.begin("acme/pipe", "a" * 40, "2026-01-01T00:00:00Z")
    pending.write(
        {
            "schema": "chartbook/snapshot/v2",
            "root": "acme/pipe",
            "code": {"commit": "a" * 40},
            "made_at": "2026-01-01T00:00:00Z",
            "records": [],
        }
    )
    records = src.records()
    assert len(records) == 1

    with mock.patch("chartbook.sharing._builds_on_there", side_effect=StoreError("boom")):
        done = sharing.copy_snapshots(records, dst)
    assert len(done.refused) == 1
    assert "boom" in done.refused[0][1]
    assert done.size_bytes == 0


# ---------------------------------------------------------------------------
# 5. store.py & stores/s3.py: _found_whole cache invalidated on unowned delete
# ---------------------------------------------------------------------------


def test_folder_store_delete_unowned_invalidates_found_whole(tmp_path):
    from chartbook.store import FolderStore, _found_whole

    store = FolderStore(tmp_path / "store")
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    stored = store.put(f)

    # Populate _found_whole for this unowned object
    assert store.incomplete(stored.content_hash, stored.size_bytes, None) is None
    assert any(seen[:2] == (str(store.root), stored.content_hash) for seen in _found_whole)

    assert store.delete_unowned(stored.content_hash) is True
    assert not any(seen[:2] == (str(store.root), stored.content_hash) for seen in _found_whole)


def test_folder_store_delete_invalidates_found_whole_for_unowned(tmp_path):
    from chartbook.store import FolderStore, _found_whole

    store = FolderStore(tmp_path / "store")
    f = tmp_path / "b.txt"
    f.write_text("world", encoding="utf-8")
    stored = store.put(f)

    assert store.incomplete(stored.content_hash, stored.size_bytes, None) is None
    assert any(seen[:2] == (str(store.root), stored.content_hash) for seen in _found_whole)

    assert store.delete(stored.content_hash) is True
    assert not any(seen[:2] == (str(store.root), stored.content_hash) for seen in _found_whole)


# ---------------------------------------------------------------------------
# 6. assets.py & check.py: bracketed ancestor dir like `Research [2026]/`
# ---------------------------------------------------------------------------


def test_assets_index_and_check_paths_in_bracketed_parent_dir(tmp_path):
    from chartbook import assets, check
    from chartbook.manifest import load_manifest

    pipe = tmp_path / "Research [2026]" / "pipe"
    pipe.mkdir(parents=True)
    (pipe / "_data").mkdir()
    (pipe / "_data" / "report.txt").write_text("hello\n", encoding="utf-8")
    (pipe / "chartbook.toml").write_text(
        '[project]\nid = "acme/p"\ntitle = "P"\nauthor = "T"\ncopyright = "2026"\n'
        '[files.report]\nname = "Report"\npath = "_data/report.txt"\n'
        '[files.missing_doc]\nname = "Missing"\npath = "_data/missing.txt"\n',
        encoding="utf-8",
    )

    df = assets.index("file/report", project_dir=pipe).collect()
    assert len(df) == 1

    manifest = load_manifest(pipe)
    problems = check.check_paths(manifest, pipe)
    missing_probs = [p for p in problems if p.table == "files.missing_doc"]
    assert len(missing_probs) == 1
    assert "file not found:" in missing_probs[0].message
    assert "no files match" not in missing_probs[0].message


# ---------------------------------------------------------------------------
# 7. formats.py & data.py: handed_name includes `inside`, stand-in SQL includes date_col
# ---------------------------------------------------------------------------


def test_handed_name_distinguishes_inside_mapping(tmp_path):
    from types import SimpleNamespace

    from chartbook import formats

    part = tmp_path / "same_bytes.ipc"
    part.write_bytes(b"ARROW")
    loc_a = SimpleNamespace(
        kind="file",
        path=tmp_path,
        format="ipc",
        options={},
        files=None,
        inside={"region=us/part.ipc": str(part)},
        listed=("region=us/part.ipc",),
    )
    loc_b = SimpleNamespace(
        kind="file",
        path=tmp_path,
        format="ipc",
        options={},
        files=None,
        inside={"region=eu/part.ipc": str(part)},
        listed=("region=eu/part.ipc",),
    )
    assert formats.handed_name(loc_a) != formats.handed_name(loc_b)


# ---------------------------------------------------------------------------
# 8. links.py: empty chartbook.links.toml returns early; malformed path doesn't crash
# ---------------------------------------------------------------------------


def test_links_resolve_returns_none_without_links_file_and_handles_bad_path(tmp_path):
    from chartbook import links
    from chartbook.resolve import AssetRef

    pipe = tmp_path / "pipe"
    pipe.mkdir()
    (pipe / "chartbook.toml").write_text(
        '[dependencies]\nrates = { path = 123 }\n',
        encoding="utf-8",
    )
    ref = AssetRef(pipeline="rates", name="yields")
    # Without chartbook.links.toml, returns None without reading chartbook.toml
    assert links.resolve(ref, pipe) is None

    # Even with an unrelated link present, malformed path=123 does not crash with TypeError
    other = tmp_path / "other"
    other.mkdir()
    (pipe / links.NAME).write_text(f'"acme/other" = "{other.as_posix()}"\n', encoding="utf-8")
    assert links.resolve(ref, pipe) is None


# ---------------------------------------------------------------------------
# 9. plotting/_overlays.py: NaT/None in datetime x-axis & date spacing
# ---------------------------------------------------------------------------


def test_overlays_x_values_to_numeric_handles_nat_and_dates():
    from chartbook.plotting._overlays import _x_values_to_numeric

    # Timestamp with NaT must produce NaN, not INT64_MIN
    ts = [pd.Timestamp("2020-01-01"), pd.NaT, pd.Timestamp("2020-01-03"), pd.Timestamp("2020-01-04")]
    arr = _x_values_to_numeric(ts)
    assert np.isnan(arr[1])
    assert np.isfinite(arr[0]) and np.isfinite(arr[2]) and np.isfinite(arr[3])
    assert arr[3] - arr[2] == pytest.approx(86400.0)

    # ISO date strings with None must produce NaN, not INT64_MIN
    strs = ["2020-01-01", None, "2020-01-03", "2020-01-04"]
    arr_s = _x_values_to_numeric(strs)
    assert np.isnan(arr_s[1])
    assert arr_s[3] - arr_s[2] == pytest.approx(86400.0)

    # Uneven datetime.date values must preserve actual date spacing (not 0, 1, 2)
    dates = [datetime.date(2020, 1, 1), datetime.date(2020, 1, 2), datetime.date(2025, 1, 1)]
    arr_d = _x_values_to_numeric(dates)
    assert (arr_d[2] - arr_d[1]) > 1000 * (arr_d[1] - arr_d[0])


# ---------------------------------------------------------------------------
# 10. cli.py: catalog disable/enable errors cleanly and enable doesn't mutate
#     catalog.toml when pipeline isn't listed
# ---------------------------------------------------------------------------


def test_cli_catalog_disable_missing_and_enable_idempotent(tmp_path):
    from chartbook.cli import main

    runner = CliRunner()

    # Missing catalog file -> clean ClickException (exit 1), not unhandled FileNotFoundError
    missing = tmp_path / "nope" / "catalog.toml"
    res = runner.invoke(main, ["catalog", "disable", "acme/rates", "--catalog", str(missing)])
    assert res.exit_code != 0
    assert res.exception is None or isinstance(res.exception, SystemExit)

    # Invalid TOML -> clean ClickException
    bad = tmp_path / "catalog.toml"
    bad.write_text("bad = [toml\n", encoding="utf-8")
    res_bad = runner.invoke(main, ["catalog", "disable", "acme/rates", "--catalog", str(bad)])
    assert res_bad.exit_code != 0
    assert res_bad.exception is None or isinstance(res_bad.exception, SystemExit)

    # Enable a pipeline not present in catalog.toml -> does not add empty [pipelines."acme/rates"]
    good = tmp_path / "good" / "catalog.toml"
    good.parent.mkdir()
    original = '[project]\ntype = "catalog"\ntitle = "Cat"\nauthor = "T"\ncopyright = "2026"\n'
    good.write_text(original, encoding="utf-8")
    res_en = runner.invoke(main, ["catalog", "enable", "acme/rates", "--catalog", str(good)])
    assert res_en.exit_code == 0, res_en.output
    assert good.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 11. versions.py & gitcache.py: trailing newline rejected by regexes
# ---------------------------------------------------------------------------


def test_versions_and_gitcache_reject_trailing_newline():
    from chartbook import gitcache, versions

    with pytest.raises(ValueError):
        versions.site_path("acme/rates", "4f2a91c-20261013T182205Z\n")
    with pytest.raises(ValueError):
        versions.version_name("a" * 40 + "\n", "2026-10-13T18:22:05Z")
    with pytest.raises(ValueError):
        versions.version_name("a" * 40, "2026-10-13T18:22:05Z\n")
    with pytest.raises(ValueError):
        gitcache.check_rev("main\n")


# ---------------------------------------------------------------------------
# 12. run.py: list-form `chartbook build --project-dir` is not falsely flagged
# ---------------------------------------------------------------------------


def test_run_in_python_allows_list_form_project_dir():
    from chartbook.run import _in_python

    code = 'subprocess.run(["chartbook", "build", "--project-dir", "../other"])\n'
    assert _in_python(code) is None

    bad_code = 'subprocess.run(["chartbook", "build", "-f"])\n'
    hit = _in_python(bad_code)
    assert hit is not None
    assert hit[1] == "chartbook build"


# ---------------------------------------------------------------------------
# 13. hashing.py & standins.py: no leaked .tmp file on replace failure
# ---------------------------------------------------------------------------


def test_hash_cache_save_cleans_temp_on_replace_error(tmp_path):
    from chartbook.hashing import HashCache

    cache_path = tmp_path / ".chartbook-hash-cache.json"
    cache = HashCache(cache_path)
    cache._used["a.csv"] = {"size": 1, "mtime_ns": 1, "sha256": "0" * 64}

    with mock.patch("chartbook.hashing.replace_when_let", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            cache.save()
    assert list(tmp_path.glob("*.tmp")) == []


def test_standins_write_cleans_temp_on_replace_error(tmp_path):
    from chartbook import standins
    from chartbook.rowhash import Compared

    target = tmp_path / "cache.json"
    compared = Compared(differ=[], outside=0, newer=0, rows=1, index_column=False, undated=False, no_date=0)

    with mock.patch("chartbook.standins.replace_when_let", side_effect=PermissionError("locked")):
        standins._write(target, "ans", compared)
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------------------
# 14. schemas/chartbook/snapshot/v2.json declares top-level `stored`
# ---------------------------------------------------------------------------


def test_snapshot_v2_schema_declares_top_level_stored():
    schema_path = Path(__file__).resolve().parents[1] / "src" / "chartbook" / "schemas" / "chartbook" / "snapshot" / "v2.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "stored" in schema["properties"]
    assert "builds_on" in schema["properties"]["stored"]["properties"]
