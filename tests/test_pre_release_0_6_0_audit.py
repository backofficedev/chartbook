"""Regression tests for the pre-release 0.6.0 audit findings."""

from __future__ import annotations

import json
import os
import subprocess
import zlib
from pathlib import Path
from unittest.mock import patch

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

from chartbook import (
    assets,
    built,
    check,
    config,
    data,
    formats,
    identity,
    lock,
    manifest,
    migrate,
    migrate_0_5,
    missing,
    multi_store,
    resolve,
    rowhash,
    sharing,
    snapshot,
    standins,
    versions,
)
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.gitcache import GitCache
from chartbook.multi_store import NamedStore, Stores, with_dependencies
from chartbook.store import FolderStore, StoreError, this_machine


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


def _make_pipeline(
    root: Path,
    pid: str = "acme/demo",
    files: dict[str, bytes] | None = None,
    manifest_text: str | None = None,
) -> Path:
    folder = root / pid.replace("/", "_")
    folder.mkdir(parents=True, exist_ok=True)
    if manifest_text is None:
        manifest_text = (
            f'[project]\nid = "{pid}"\n\n'
            '[files.data]\npath = "data.bin"\n'
        )
    (folder / "chartbook.toml").write_text(manifest_text, encoding="utf-8")
    for rel, content in (files or {"data.bin": b"v1" * 100}).items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(folder, "init", "-b", "main")
    _git(folder, "add", ".")
    _git(folder, "commit", "-m", "initial")
    return folder


# ---------------------------------------------------------------------------
# P0-1: migrate.plan refuses v3 / half-migrated v2->v3 stores
# ---------------------------------------------------------------------------


def test_p0_1_v2_migrate_refuses_v3_and_half_moved_v3_stores(tmp_path):
    store = FolderStore(tmp_path / "v3_store")
    p = _make_pipeline(tmp_path, pid="acme/p01")
    snapshot.make(p, store=store, complete=True, made_at="2026-01-01T00:00:00Z")

    # Even if store.json is deleted, migrate.plan (0.2 -> 0.5) must return nothing to migrate
    # and migrate._switch must never delete non-40-hex pipeline folders under snapshots/
    (store.root / "store.json").unlink()
    planned = migrate.plan(store.root)
    assert planned.records == []
    assert planned.objects == 0
    assert (store.root / "snapshots" / "acme+p01").is_dir()


# ---------------------------------------------------------------------------
# P0-2 & P0-3: Hive partition key coercion when key is also in parquet files
# ---------------------------------------------------------------------------


def test_p0_2_and_p0_3_hive_partition_key_coercion_preserves_strings_and_types(tmp_path):
    # A time of day in a folder name holds a colon, which Windows has no name for
    if os.name == "nt":
        pytest.skip("Windows has no folder name with a colon in it")
    # Put dataset under a `parent=above` folder so formats._hive uses _by_file and formats.sql uses _folder_sql
    parent = tmp_path / "parent=above"
    dataset = parent / "hive_ds"
    for code, flag, t_val in [
        ("007", True, "09:30:00"),
        ("042", False, "15:45:00"),
    ]:
        part = dataset / f"code={code}" / f"flag={'true' if flag else 'false'}" / f"tm={t_val}"
        part.mkdir(parents=True, exist_ok=True)
        df = pl.DataFrame({
            "code": [code],
            "flag": [flag],
            "tm": [pl.Series([t_val]).str.to_time()[0]],
            "val": [10 if flag else 20],
        })
        df.write_parquet(part / "part.parquet")

    # formats.scan and formats.sql must preserve leading zeros ("007", "042"), bools, and Time
    lf = formats.scan(dataset, "parquet")
    out = lf.collect().sort("code")
    assert out["code"].to_list() == ["007", "042"]
    assert out["flag"].to_list() == [True, False]
    assert out["tm"].dtype == pl.Time

    loc = resolve.FileLocation(path=dataset, format="parquet")
    table_sql = formats.sql(loc)
    con = duckdb.connect(":memory:")
    try:
        sql_df = con.sql(f"SELECT code, flag, val FROM {table_sql} ORDER BY code").pl()
        assert sql_df["code"].to_list() == ["007", "042"]
        assert sql_df["flag"].to_list() == [True, False]
    finally:
        con.close()

    # rowhash.hash_rows must also preserve string keys and time keys without crashing
    hashed = rowhash.hash_rows(rowhash.Table(dataset))
    assert hashed.rows.get(rowhash.ALL) is not None


# ---------------------------------------------------------------------------
# P0-4: Stand-in atomicity across unlocked / unpinned assets
# ---------------------------------------------------------------------------


def test_p0_4_unlocked_read_raises_when_pinned_bytes_missing_and_no_standin(tmp_path, monkeypatch):
    store = FolderStore(tmp_path / "store")
    monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
    up_manifest = (
        '[project]\nid = "acme/up"\n\n'
        '[dataframes.prices]\npath = "prices.parquet"\n\n'
        '[charts.plot]\npath = "plot.html"\n'
    )
    up_dir = tmp_path / "up"
    up_dir.mkdir()
    (up_dir / "chartbook.toml").write_text(up_manifest, encoding="utf-8")
    (up_dir / ".gitignore").write_text("prices.parquet\nplot.html\n", encoding="utf-8")
    pl.DataFrame({"d": ["2026-01-01"], "v": [1]}).write_parquet(up_dir / "prices.parquet")
    (up_dir / "plot.html").write_text("<html>v1</html>", encoding="utf-8")
    _git(up_dir, "init", "-b", "main")
    _git(up_dir, "add", ".")
    _git(up_dir, "commit", "-m", "v1")
    snap1 = snapshot.make(up_dir, store=store, complete=True, made_at="2026-01-01T00:00:00Z").snapshot

    down_dir = tmp_path / "down"
    down_dir.mkdir()
    (down_dir / "chartbook.toml").write_text(
        '[project]\nid = "acme/down"\n\n[dependencies]\n"acme/up" = {}\n',
        encoding="utf-8",
    )
    _git(down_dir, "init", "-b", "main")
    _git(down_dir, "add", ".")
    _git(down_dir, "commit", "-m", "down")
    lock.pin(down_dir, store=store)

    # Make a second snapshot at the SAME commit that differs in prices.parquet, then remove snap1
    pl.DataFrame({"d": ["2026-01-01"], "v": [999]}).write_parquet(up_dir / "prices.parquet")
    (up_dir / "plot.html").write_text("<html>v2-wrong</html>", encoding="utf-8")
    snapshot.make(up_dir, store=store, complete=True, made_at="2026-01-03T00:00:00Z")
    store.remove_snapshot(snap1.path)
    store.tidy_pipeline("acme/up")

    # Reading the unlocked chart from acme/up must raise AssetNotPinnedError, not return plot.html from snap2!
    with pytest.raises(AssetNotPinnedError):
        resolve.resolve("acme/up:chart/plot", start_dirs=[down_dir])


# ---------------------------------------------------------------------------
# P0-5: _sql_up_to checks all files (>8) and case-insensitive column collisions
# ---------------------------------------------------------------------------


def test_p0_5_sql_up_to_checks_beyond_8_files(tmp_path):
    ds = tmp_path / "many_parts"
    ds.mkdir()
    for i in range(10):
        df = pl.DataFrame({"date": [pl.Series([f"2026-01-{i + 1:02d}"]).str.to_date()[0]], "v": [i]})
        if i == 9:
            # 10th file also has a case-colliding DATE column
            df = pl.DataFrame({
                "DATE": [pl.Series([f"2026-01-{i + 1:02d}"]).str.to_date()[0]],
                "date": [pl.Series([f"2026-01-{i + 1:02d}"]).str.to_date()[0]],
                "v": [i],
            })
        df.write_parquet(ds / f"part-{i:02d}.parquet")

    loc = resolve.FileLocation(path=ds, format="parquet")
    # Because file #10 has both DATE and date, _sql_up_to must return None so Polars handles the filter
    assert data._sql_up_to(loc, "date", "2026-01-05") is None


# ---------------------------------------------------------------------------
# P0-6: _held_against_its_build checks [files.*] and [notes.*] when no dataframe/chart/model exists
# ---------------------------------------------------------------------------


def test_p0_6_held_against_its_build_checks_files_only_pipeline(tmp_path, monkeypatch):
    store = FolderStore(tmp_path / "store")
    monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
    manifest_text = (
        '[project]\nid = "acme/filesonly"\n\n'
        '[scripts]\nbuild = "python -c \\"open(\'out.bin\', \'wb\').write(b\'built\')\\""\n\n'
        '[files.out]\npath = "out.bin"\n'
    )
    p = _make_pipeline(tmp_path, pid="acme/filesonly", files={"out.bin": b"handwritten"}, manifest_text=manifest_text)
    # No build note exists, and out.bin is on disk -> snapshot without --as-is must refuse
    res = CliRunner().invoke(main, ["snapshot", "--project-dir", str(p)])
    assert res.exit_code != 0
    assert "chartbook run" in res.output or "--as-is" in res.output


# ---------------------------------------------------------------------------
# P0-7: Credential scrubbing on URLs with leading whitespace and git errors
# ---------------------------------------------------------------------------


def test_p0_7_strip_url_credentials_handles_leading_whitespace_and_git_errors(tmp_path):
    assert identity.strip_url_credentials("  https://secret-token@github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert identity.strip_url_credentials("\thttp://user:hunter2@example.com/a/b") == "http://example.com/a/b"

    cache = GitCache(root=tmp_path / "gitcache")
    with pytest.raises(Exception) as exc_info:
        cache._git("ls-remote", "https://myuser:supersecret@127.0.0.1:1/org/repo.git")
    assert "supersecret" not in str(exc_info.value)
    assert "myuser" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# P0-8 & P1-10: Stores.add_root resilience when store[0] fails & stale note removal
# ---------------------------------------------------------------------------


def test_p0_8_and_p1_10_stores_add_root_continues_on_error_and_removes_stale_notes(tmp_path):
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"111"})
    p2 = _make_pipeline(tmp_path, pid="acme/p2", files={"data.bin": b"222"})
    t1 = snapshot.make(p1, store=s1, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    t2 = snapshot.make(p2, store=s2, complete=True, made_at="2026-01-01T00:00:00Z").snapshot

    stores = Stores([NamedStore("one", str(s1.root), s1), NamedStore("two", str(s2.root), s2)])
    lockfile = tmp_path / "proj" / "chartbook.lock"
    machine = this_machine()
    h1 = next(iter(t1.hashes()))
    h2 = next(iter(t2.hashes()))

    # Initially pin both s1 and s2
    stores.add_root(lockfile, [h1, h2], [("acme/p1", t1.commit, t1.made_at), ("acme/p2", t2.commit, t2.made_at)], machine=machine)
    assert s1.root_of(lockfile, machine) is not None
    assert s2.root_of(lockfile, machine) is not None

    # Now drop p2 so only h1 (in s1) is pinned: s2's stale note must be removed!
    stores.add_root(lockfile, [h1], [("acme/p1", t1.commit, t1.made_at)], machine=machine)
    assert s1.root_of(lockfile, machine) is not None
    assert s2.root_of(lockfile, machine) is None
    assert stores.note_matches(lockfile, [h1], [("acme/p1", t1.commit, t1.made_at)], machine, ())

    # If s1 raises PermissionError during add_root for [h1, h2], s2 still receives its note before the error is raised
    with patch.object(s1, "add_root", side_effect=PermissionError("s1 read-only")):
        with pytest.raises(PermissionError):
            stores.add_root(lockfile, [h1, h2], [("acme/p1", t1.commit, t1.made_at), ("acme/p2", t2.commit, t2.made_at)], machine=machine)
    assert s2.root_of(lockfile, machine) is not None


# ---------------------------------------------------------------------------
# P1-3: Stores._deduplicated strips top-level "stored"
# ---------------------------------------------------------------------------


def test_p1_3_stores_deduplicated_strips_top_level_stored(tmp_path):
    rec1 = tmp_path / "r1.json"
    rec2 = tmp_path / "r2.json"
    base = {"schema": "chartbook/snapshot/v1", "pipeline": "acme/p", "commit": "a" * 40, "made_at": "2026-01-01T00:00:00Z", "records": []}
    rec1.write_text(json.dumps({**base, "stored": {"increment": {"builds_on": "20260101"}}}), encoding="utf-8")
    rec2.write_text(json.dumps(base), encoding="utf-8")
    assert len(Stores._deduplicated([rec1, rec2])) == 1


# ---------------------------------------------------------------------------
# P1-4: lock.see_to_the_floor updates build attestation note for chartbook.toml
# ---------------------------------------------------------------------------


def test_p1_4_floor_raise_preserves_build_note_validity(tmp_path):
    manifest_text = (
        '[project]\nid = "acme/floor"\nrequires_chartbook = ">=0.5"\n\n'
        '[scripts]\nbuild = "echo ok"\n\n'
        '[files.out]\npath = "out.txt"\n'
    )
    p = _make_pipeline(tmp_path, pid="acme/floor", files={"out.txt": b"hello"}, manifest_text=manifest_text)
    # Write a 0.6 lockfile before the build (as `chartbook run` pins before building)
    (p / "chartbook.lock").write_text(
        json.dumps({
            "schema": lock.SCHEMA,
            "chartbook_version": "0.6.0",
            "root": "acme/floor",
            "dependencies": [],
            "assets": [{
                "id": "acme/dep:df",
                "kind": "Dataframe",
                "pipeline": "acme/dep",
                "content_hash": "sha256:" + "a" * 64,
                "size_bytes": 10,
                "ref": {"pipeline": "acme/dep", "kind": "dataframe", "name": "df"},
                "location": {"kind": "file", "path": "df.parquet"},
                "since": {"commit": "b" * 40, "made_at": "2026-01-01T00:00:00Z", "content_hash": "sha256:" + "c" * 64, "rows": ["2026"]},
            }],
        }),
        encoding="utf-8",
    )
    building = built.began(p, "acme/floor")
    built.finished(building)
    assert built.check(p, "acme/floor") is True

    # Now see_to_the_floor raises requires_chartbook in chartbook.toml
    floor = lock.see_to_the_floor(p, write=True)
    assert floor is not None and floor.written
    # Build attestation must still pass!
    assert built.check(p, "acme/floor") is True


# ---------------------------------------------------------------------------
# P1-16, P1-17, P1-18, P2-14, P2-15: rowhash & table edge cases
# ---------------------------------------------------------------------------


def test_p1_17_text_bytes_zlib_header_and_corrupt_gz_fallback(tmp_path):
    # A valid zlib-compressed CSV (0x78 0x9c) must unpack to len(raw_csv)
    raw_csv = b"a,b\n" + b"1,2\n" * 500
    z_file = tmp_path / "data.zcsv"
    z_file.write_bytes(zlib.compress(raw_csv))
    assert rowhash._text_bytes(z_file, rowhash.MOST_BYTES) == len(raw_csv)

    # Plain UTF-8 text starting with 'x,' (0x78 0x2c, which has FDICT=1 and % 31 == 0!) must not be treated as zlib
    plain_x = tmp_path / "x.csv"
    plain_x.write_bytes(b"x,y\n1,2\n")
    assert rowhash._text_bytes(plain_x, rowhash.MOST_BYTES) == len(b"x,y\n1,2\n")

    # A fake zlib header with corrupt payload must fall back to file size on disk without raising zlib.error
    bad_z = tmp_path / "bad.z"
    bad_z.write_bytes(b"\x78\x9ccorrupt-bytes-not-deflate")
    assert rowhash._text_bytes(bad_z, rowhash.MOST_BYTES) == bad_z.stat().st_size


def test_p1_18_parquet_batches_handles_schema_evolution_missing_column(tmp_path):
    ds = tmp_path / "evolved"
    ds.mkdir()
    pl.DataFrame({"a": [1, 2], "b": ["x", "y"]}).write_parquet(ds / "part1.parquet")
    pl.DataFrame({"a": [3, 4]}).write_parquet(ds / "part2.parquet")

    h = rowhash.hash_rows(rowhash.Table(ds))
    assert h.rows.get(rowhash.ALL) is not None


def test_p2_14_hash_in_undated_table_with_period_rows_skips_whole_hash(tmp_path):
    f = tmp_path / "undated.parquet"
    pl.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}).write_parquet(f)

    with patch.object(rowhash, "_whole", side_effect=AssertionError("_whole must not be called for undated period query")):
        compared = rowhash.hash_in(
            rowhash.Table(f),
            "date",
            {"2026-01-01/2026-12-31": "sha256:" + "a" * 64},
            "2026-12-31",
        )
    assert compared.undated is True
    assert compared.differ == ["2026-01-01/2026-12-31"]


def test_p2_15_arrow_string_view_binary_length(tmp_path):
    f = tmp_path / "view.parquet"
    arr = pa.array(["alpha", "beta", "gamma"], type=pa.string_view())
    tbl = pa.table({"s": arr, "n": [1, 2, 3]})
    pq.write_table(tbl, f)

    h = rowhash.hash_rows(rowhash.Table(f))
    assert h.rows.get(rowhash.ALL) is not None


# ---------------------------------------------------------------------------
# P1-19: resolve(..., pipeline=...) in batch mode outside a pipeline refuses before touching catalog
# ---------------------------------------------------------------------------


def test_p1_19_resolve_pipeline_outside_project_in_batch_does_not_create_catalog(tmp_path, monkeypatch):
    home = tmp_path / "clean_home"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    monkeypatch.setenv("CHARTBOOK_BATCH", "1")
    outside = tmp_path / "not_a_pipeline"
    outside.mkdir()

    with pytest.raises(AssetNotPinnedError, match="no pipeline"):
        resolve.resolve("prices", pipeline="acme/up", start_dirs=[outside])
    assert not (home / "catalog.toml").exists()


# ---------------------------------------------------------------------------
# P2-31 & P2-32: Malformed TOML non-dict guards & set_default_catalog_path
# ---------------------------------------------------------------------------


def test_p2_31_and_p2_32_toml_non_dict_guards_and_catalog_toml_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)

    # catalog.toml without explicit type = "catalog" should be accepted by set_default_catalog_path
    cat_dir = tmp_path / "mycat"
    cat_dir.mkdir()
    cat_file = cat_dir / "catalog.toml"
    cat_file.write_text('[catalog]\nname = "Demo"\n', encoding="utf-8")
    config.set_default_catalog_path(cat_file)
    assert config.get_default_catalog_path() == cat_file.resolve()

    # Non-dict sections in chartbook.toml must return cleanly without AttributeError
    bad_dir = tmp_path / "bad_manifest"
    bad_dir.mkdir()
    (bad_dir / "chartbook.toml").write_text('project = "not-a-table"\ndataframes = 123\ndependencies = "none"\n', encoding="utf-8")
    assert all(v == [] for v in resolve.declared_assets(bad_dir).values())
    assert with_dependencies(bad_dir, store=FolderStore(tmp_path / "s")) is not None


# ---------------------------------------------------------------------------
# Follow-up pre-release audit fixes (URL get_data_path, Date/Datetime Hive
# coercion, write_note multi-store stale note removal, note_matches with
# snapshots=None, batch resolve validation, local assets.index without store)
# ---------------------------------------------------------------------------


def test_get_data_path_with_repository_url_and_batch_resolve_validation(tmp_path, monkeypatch):
    monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
    st = FolderStore(tmp_path / "store")
    p = tmp_path / "p"
    p.mkdir()
    (p / "chartbook.toml").write_text(
        '[project]\nid = "acme/rates"\nrepo_url = "https://github.com/acme/rates"\n'
        '[dataframes.df]\npath = "df.parquet"\n',
        encoding="utf-8",
    )
    pl.DataFrame({"x": [1]}).write_parquet(p / "df.parquet")
    _git(p, "init", "-b", "main")
    _git(p, "remote", "add", "origin", "https://github.com/acme/rates")
    _git(p, "add", ".")
    _git(p, "commit", "-m", "init")
    snapshot.make(p, store=st, complete=True, made_at="2026-01-01T00:00:00Z")

    cat = tmp_path / "catalog.toml"
    cat.write_text(f'[stores.default]\nurl = {str(st.root)!r}\n', encoding="utf-8")

    found_path = data.get_data_path("https://github.com/acme/rates", "df", catalog_path=cat)
    assert found_path.is_file()

    # In batch mode outside a pipeline, invalid asset names still raise ValueError,
    # and URL pipeline resolution through an existing catalog names acme/rates (not None)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CHARTBOOK_BATCH", "1")
    with pytest.raises(ValueError, match="Invalid asset name"):
        resolve.resolve("bad/name", pipeline="acme/rates", catalog_path=cat, start_dirs=[outside])
    with pytest.raises(AssetNotPinnedError, match="declare acme/rates"):
        resolve.resolve("df", pipeline="https://github.com/acme/rates", catalog_path=cat, start_dirs=[outside])


def test_coerced_boolean_words_keep_their_meaning():
    """yes, t, y and 1 are true. A word that is not one of the boolean words is null, and is not false."""
    written = ["true", "TRUE", "yes", "Yes", "t", "y", "1", "false", "no", "f", "n", "0", "maybe", "YES"]
    expected = [True, True, True, True, True, True, True, False, False, False, False, False, None, True]
    assert formats._coerced_key_values(pl.String, written, written, pl.Boolean) == expected
    assert formats._coerced_key_values(pl.Int64, [1, 0], ["1", "0"], pl.Boolean) == [True, False]


def test_hive_boolean_partition_words_survive_a_read(tmp_path):
    """A boolean column partitioned as yes/t/y is that value in a scan and in SQL, including when a key sits above the folder."""
    root = tmp_path / "parent=above" / "ds"
    words = {"yes": True, "no": False, "t": True, "f": False, "y": True, "n": False, "1": True, "0": False}
    for label, bit in words.items():
        part = root / f"flag={label}"
        part.mkdir(parents=True)
        pl.DataFrame({"flag": [bit], "v": [1]}).write_parquet(part / "a.parquet")

    got = formats.scan(root, "parquet").collect()
    # Four true words and four false ones. Before the fix every word but "true" came back false.
    assert sorted(got["flag"].to_list()) == sorted(words.values())

    sql = formats.sql(resolve.FileLocation(path=root, format="parquet"))
    con = duckdb.connect()
    try:
        out = con.sql(f"SELECT flag FROM {sql}").pl()
    finally:
        con.close()
    assert sorted(out["flag"].to_list()) == sorted(words.values())
    assert "'False'::BOOLEAN" in sql  # no, f, n, 0
    assert sql.count("'True'::BOOLEAN") == 4  # yes, t, y, 1

    alone = tmp_path / "yes-cap"
    part = alone / "flag=YES"
    part.mkdir(parents=True)
    pl.DataFrame({"flag": [True], "v": [1]}).write_parquet(part / "a.parquet")
    assert formats.scan(alone, "parquet").collect()["flag"].to_list() == [True]


def test_coerced_key_values_handles_dates_and_naive_datetimes():
    from datetime import date, datetime, timezone

    assert formats._coerced_key_values(
        pl.String, ["2024-01-01"], ["2024-01-01"], pl.Date
    ) == [date(2024, 1, 1)]
    assert formats._coerced_key_values(
        pl.String, ["2024-01-01T00:00:00"], ["2024-01-01T00:00:00"], pl.Datetime("us")
    ) == [datetime(2024, 1, 1, 0, 0)]
    assert formats._coerced_key_values(
        pl.Datetime("us", "UTC"),
        [datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)],
        ["2024-01-01T00:00:00Z"],
        pl.Datetime("us"),
    ) == [datetime(2024, 1, 1, 0, 0)]
    assert formats._coerced_key_values(
        pl.Date, [None, date(2024, 1, 1)], ["", "2024-01-01"], pl.Datetime("us")
    ) == [None, datetime(2024, 1, 1, 0, 0)]


def test_gc_names_what_went_when_the_note_cannot_be_forgotten(tmp_path, monkeypatch):
    """A note that cannot be forgotten after the removal does not report that nothing was removed."""
    store = FolderStore(tmp_path / "store")
    monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
    pipeline = _make_pipeline(tmp_path, pid="acme/gcnote")
    taken = snapshot.make(pipeline, store=store, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    lockfile = tmp_path / "proj" / "chartbook.lock"
    machine = this_machine()
    store.add_root(lockfile, taken.hashes(), [("acme/gcnote", taken.commit, taken.made_at)], machine=machine)
    (note,) = store.roots()
    done = lock.GcDone(snapshots=2, objects=1, freed_bytes=4096, pinned=1)

    def boom(*_args, **_kwargs):
        raise OSError("note is busy")

    monkeypatch.setattr(lock, "carry_out_gc", lambda *_args, **_kwargs: done)
    monkeypatch.setattr("chartbook.cli._forget_root", boom)
    result = CliRunner().invoke(main, ["store", "gc", "--forget-note", note.note, "--yes", "--keep-days", "0"])
    assert result.exit_code == 1, result.output
    assert "Nothing was removed." not in result.output
    assert "Removed 2 snapshot(s), 1 snapshot(s) a pin made from a repository and 1 object(s), 4.0 KB." in result.output
    assert note.note in result.output
    assert "is still there" in result.output
    assert store.root_of(lockfile, machine) is not None


def test_write_note_cleans_stale_store_and_note_matches_handles_none_snapshots(tmp_path):
    s1 = FolderStore(tmp_path / "s1")
    s2 = FolderStore(tmp_path / "s2")
    p1 = _make_pipeline(tmp_path, pid="acme/p1", files={"data.bin": b"111"})
    p2 = _make_pipeline(tmp_path, pid="acme/p2", files={"data.bin": b"222"})
    t1 = snapshot.make(p1, store=s1, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    t2 = snapshot.make(p2, store=s2, complete=True, made_at="2026-01-01T00:00:00Z").snapshot

    stores = Stores([NamedStore("one", str(s1.root), s1), NamedStore("two", str(s2.root), s2)])
    lf = tmp_path / "consumer" / "chartbook.lock"
    lf.parent.mkdir(parents=True, exist_ok=True)
    m = this_machine()
    h1 = next(iter(t1.hashes()))
    h2 = next(iter(t2.hashes()))

    locked_both = lock.Lock(
        root="consumer",
        assets={
            "acme/p1:data": {"id": "acme/p1:data", "kind": "File", "pipeline": "acme/p1", "content_hash": h1},
            "acme/p2:data": {"id": "acme/p2:data", "kind": "File", "pipeline": "acme/p2", "content_hash": h2},
        },
    )
    lock.write_note(lf, locked_both, stores, machine=m)
    assert s1.root_of(lf, m) is not None and s2.root_of(lf, m) is not None

    # Dropping p2 via write_note must remove the stale note from s2
    locked_one = lock.Lock(
        root="consumer",
        assets={
            "acme/p1:data": {"id": "acme/p1:data", "kind": "File", "pipeline": "acme/p1", "content_hash": h1},
        },
    )
    lock.write_note(lf, locked_one, stores, machine=m)
    assert s1.root_of(lf, m) is not None
    assert s2.root_of(lf, m) is None

    # If s1 raises PermissionError during write_note, s2 still receives its note
    with patch.object(s1, "add_root", side_effect=PermissionError("s1 read-only")):
        with pytest.raises(PermissionError):
            lock.write_note(lf, locked_both, stores, machine=m)
    assert s2.root_of(lf, m) is not None

    # note_matches with snapshots=None must match a note written with snapshots=None
    s2.remove_root(lf, m)
    s1.add_root(lf, [h1], None, machine=m)
    assert stores.note_matches(lf, [h1], None, m, ()) is True


def test_local_assets_index_does_not_open_store(tmp_path, monkeypatch):
    p = _make_pipeline(tmp_path, pid="acme/local_idx", files={"data.bin": b"abc"})
    # Point CHARTBOOK_STORE at an invalid store URL: local assets.index should not touch default_store()
    monkeypatch.setenv("CHARTBOOK_STORE", "invalid-scheme://nowhere")
    df = assets.index("file/data", project_dir=p).collect()
    assert len(df) == 1
    assert df["size_bytes"].to_list() == [3]

