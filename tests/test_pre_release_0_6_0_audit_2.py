"""Regression tests for the second pre-release 0.6.0 audit pass."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import (
    catalog_config,
    config,
    create_data_glimpses,
    data,
    diagnostics,
    formats,
    incremental,
    lock,
    manifest,
    missing,
    plotting,
    publish,
    resolve,
    run as run_mod,
    sharing,
    snapshot,
    utils,
)
from chartbook.cli import main
from chartbook.gitcache import GitCache
from chartbook.multi_store import NamedStore, Stores
from chartbook.path_validation import ShellEnvironment, diagnose_path
from chartbook.store import FolderStore, ObjectNotFoundError, StoreError
from chartbook.stores.s3 import S3Store


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    return proc.stdout.strip()


def _init_pipeline(folder: Path, pid: str = "acme/p", extra_toml: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "README.md").write_text(f"# {pid}\n", encoding="utf-8")
    (folder / "_data").mkdir(exist_ok=True)
    pl.DataFrame({"x": [1, 2], "y": [3, 4]}).write_parquet(folder / "_data" / "df1.parquet")
    (folder / "chartbook.toml").write_text(
        f"""
[project]
id = "{pid}"
name = "{pid}"
readme = "./README.md"

[dataframes.df1]
path = "./_data/df1.parquet"
docs = "df1"
{extra_toml}
""".lstrip(),
        encoding="utf-8",
    )
    return folder


# ---------------------------------------------------------------------------
# 1. lock._fetch restores pinned git commits no longer on a branch or tag
# ---------------------------------------------------------------------------
def test_lock_fetch_restores_orphaned_git_commit(tmp_path):
    remote = tmp_path / "remote"
    _init_pipeline(remote, pid="acme/up")
    _git(remote, "init", "-b", "main")
    _git(remote, "add", ".")
    _git(remote, "commit", "-m", "init")
    _git(remote, "checkout", "-b", "feat")
    pl.DataFrame({"x": [10, 20], "y": [30, 40]}).write_parquet(remote / "_data" / "df1.parquet")
    _git(remote, "add", ".")
    _git(remote, "commit", "-m", "feat")
    feat_sha = _git(remote, "rev-parse", "HEAD")
    _git(remote, "checkout", "main")

    consumer = tmp_path / "consumer"
    _init_pipeline(
        consumer,
        pid="acme/down",
        extra_toml=f'\n[dependencies]\nup = {{ git = "{remote.as_uri()}", rev = "feat" }}\n',
    )
    store1 = FolderStore(tmp_path / "store1")
    gc1 = GitCache(tmp_path / "gc1")
    rep1 = lock.pin(consumer, store=store1, git_cache=gc1)
    assert any(e.status == "pinned" for e in rep1.events)

    # Delete the feature branch on the remote so feat_sha is unreachable from refs
    _git(remote, "branch", "-D", "feat")

    # Fresh machine: empty store and fresh git cache
    store2 = FolderStore(tmp_path / "store2")
    gc2 = GitCache(tmp_path / "gc2")
    rep2 = lock.pin(consumer, store=store2, git_cache=gc2)
    assert not any(e.status in ("unfetched", "lost") for e in rep2.events), rep2.events
    assert any(e.status == "fetched" and feat_sha[:7] in e.detail for e in rep2.events)


# ---------------------------------------------------------------------------
# 2. missing._Walk.needs does not set folder to a deleted monorepo subdirectory
# ---------------------------------------------------------------------------
def test_missing_walk_deleted_monorepo_subdir_no_broken_git_c(tmp_path):
    mono = tmp_path / "mono"
    _init_pipeline(mono / "old_b", pid="acme/b")
    _init_pipeline(
        mono / "a",
        pid="acme/a",
        extra_toml='\n[dependencies]\nb = { path = "../old_b" }\n',
    )
    _git(mono, "init", "-b", "main")
    _git(mono, "add", ".")
    _git(mono, "commit", "-m", "c1")
    c1 = _git(mono, "rev-parse", "HEAD")

    # Pin consumer to mono/a at c1 (where a has an unpinned dep on ../old_b), then delete old_b in c2
    store_pin = FolderStore(tmp_path / "store_pin")
    consumer = tmp_path / "consumer"
    _init_pipeline(
        consumer,
        pid="acme/consumer",
        extra_toml=f'\n[dependencies]\na = {{ path = "{(mono / "a").as_posix()}" }}\n',
    )
    lock.write_lock(
        lock.Lock(
            root="acme/consumer",
            dependencies=[{
                "id": "a",
                "via": "path",
                "pinned_from": "acme/a",
                "snapshot": "2026-01-01T00:00:00Z",
                "location": {"kind": "path", "path": (mono / "a").as_posix(), "commit": c1},
            }],
            assets={
                "a:dataframe/df1": {
                    "id": "a:dataframe/df1",
                    "kind": "Dataframe",
                    "content_hash": "sha256:" + "1" * 64,
                },
            },
        ),
        consumer / "chartbook.lock",
    )

    _git(mono, "rm", "-rf", "old_b")
    _git(mono, "commit", "-m", "delete old_b")

    empty_store = FolderStore(tmp_path / "empty_store")
    listing = missing.find(consumer, store=empty_store)
    text = "\n".join(missing.said(listing))
    assert f"git -C {mono / 'old_b'}" not in text
    assert "there is no folder at" not in text
    assert c1[:7] in text


# ---------------------------------------------------------------------------
# 3. resolve.resolve(catalog_path=...) honors [stores] from pipeline & legacy catalog
# ---------------------------------------------------------------------------
def test_resolve_with_store_catalog_from_pipeline_and_legacy_catalog(tmp_path, monkeypatch):
    default_s = FolderStore(tmp_path / "default_store")
    custom_s = FolderStore(tmp_path / "custom_store")
    monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
    monkeypatch.setattr("chartbook.store.default_store", lambda *a, **kw: default_s)

    up = _init_pipeline(tmp_path / "up", pid="acme/up")
    _git(up, "init", "-b", "main")
    _git(up, "add", ".")
    _git(up, "commit", "-m", "init")
    snapshot.make(up, store=custom_s, complete=True)

    store_cat = tmp_path / "store_cat"
    store_cat.mkdir()
    (store_cat / "catalog.toml").write_text(
        f'[catalog]\nname = "Cat"\n[stores.custom]\nurl = "{custom_s.root.as_posix()}"\n',
        encoding="utf-8",
    )

    # From inside an unrelated pipeline (interactive mode)
    unrelated = _init_pipeline(tmp_path / "unrelated", pid="acme/unrelated")
    loc = resolve.resolve(
        "df1",
        pipeline="acme/up",
        catalog_path=store_cat / "catalog.toml",
        start_dirs=[unrelated],
    )
    assert loc.kind == "file"

    # From inside a legacy catalog (chartbook.toml with type = "catalog")
    legacy_cat = tmp_path / "legacy_cat"
    legacy_cat.mkdir()
    (legacy_cat / "README.md").write_text("# Legacy\n", encoding="utf-8")
    (legacy_cat / "chartbook.toml").write_text(
        '[project]\ntype = "catalog"\nid = "legacy"\nname = "Legacy"\nreadme = "./README.md"\n',
        encoding="utf-8",
    )
    loc2 = resolve.resolve(
        "df1",
        pipeline="acme/up",
        catalog_path=store_cat / "catalog.toml",
        start_dirs=[legacy_cat],
    )
    assert loc2.kind == "file"


# ---------------------------------------------------------------------------
# 4. data.sql single-pass substitution with brace-containing directory path
# ---------------------------------------------------------------------------
def test_data_sql_path_containing_other_ref_token(tmp_path):
    proj = tmp_path / "proj_{b}"
    _init_pipeline(
        proj,
        pid="acme/braces",
        extra_toml='\n[dataframes.b]\npath = "./_data/b.parquet"\ndocs = "b"\n',
    )
    pl.DataFrame({"x": [1, 2], "z": [10, 20]}).write_parquet(proj / "_data" / "b.parquet")
    out = data.sql("select df1.x, df1.y, b.z from {df1} as df1 join {b} as b using (x)", project_dir=proj).collect()
    assert out.height == 2
    assert sorted(out["z"].to_list()) == [10, 20]


# ---------------------------------------------------------------------------
# 5. lock.carry_out_gc protects kept_bases and kept_back for pinned_delete
# ---------------------------------------------------------------------------
def test_carry_out_gc_protects_pinned_delete_base_and_hashes(tmp_path, monkeypatch):
    store = FolderStore(tmp_path / "store")
    p = _init_pipeline(tmp_path / "p", pid="acme/gc")
    _git(p, "init", "-b", "main")
    _git(p, "add", ".")
    _git(p, "commit", "-m", "init")
    base = snapshot.make(p, store=store, complete=True, made_at="2026-01-01T00:00:00Z").snapshot
    inc = snapshot.make(p, store=store, complete=False, made_at="2026-01-02T00:00:00Z").snapshot

    # Simulate an increment that fails to delete while its base is in pinned_delete
    plan = lock.GcPlan(
        keep_days=0,
        snapshots_delete=[(inc, "old")],
        pinned_delete=[(base, "old pin")],
    )
    monkeypatch.setattr(lock, "plan_gc", lambda *_a, **_kw: plan)
    monkeypatch.setattr(store, "builds_on", lambda rec: base.path if rec == inc.path else None)

    removed_paths = []
    real_remove = snapshot.remove

    def fake_remove(s, taken):
        if taken.path == inc.path:
            raise OSError("locked increment")
        removed_paths.append(taken.path)
        return real_remove(s, taken)

    monkeypatch.setattr(snapshot, "remove", fake_remove)
    with pytest.raises(lock.GcError):
        lock.carry_out_gc(plan, store)
    assert base.path not in removed_paths
    assert Path(base.path).is_file()


# ---------------------------------------------------------------------------
# 6. lock._noted_as treats CI=false and CI=0 as non-CI
# ---------------------------------------------------------------------------
def test_noted_as_false_and_zero_ci(monkeypatch):
    monkeypatch.delenv(config.MACHINE_ENV_VAR, raising=False)
    for val in ("false", "FALSE", "0", ""):
        monkeypatch.setenv("CI", val)
        assert lock._noted_as() is None
    monkeypatch.setenv("CI", "true")
    assert lock._noted_as() == ""


# ---------------------------------------------------------------------------
# 7. multi_store age_of & verify + S3Store.listing
# ---------------------------------------------------------------------------
def test_multi_store_age_of_and_verify_when_unreachable(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    stores = Stores([NamedStore("gone", str(missing_dir), FolderStore(missing_dir), create=False)])
    fake_hash = "sha256:" + "0" * 64

    with pytest.raises(ObjectNotFoundError):
        stores.age_of(fake_hash)

    problems = stores.verify([fake_hash])
    assert len(problems) == 1
    assert problems[0].content_hash == fake_hash


def test_s3_store_listing_no_name_error():
    s3 = S3Store.__new__(S3Store)
    s3._seen = lambda: None
    s3._held = lambda _seen, _h: []
    assert s3.listing("sha256:" + "0" * 64, single=True) is None


# ---------------------------------------------------------------------------
# 8. incremental glob escaping with bracketed directory name
# ---------------------------------------------------------------------------
def test_incremental_glob_with_brackets_in_base_dir(tmp_path):
    proj = _init_pipeline(
        tmp_path / "Research [2026]" / "pipe",
        pid="acme/bracket",
        extra_toml='\n[dataframes.globdf]\npath = "./_data/*.parquet"\ndocs = "g"\n',
    )
    loaded = manifest.load_manifest(proj)
    inputs = incremental.pipeline_input_files(loaded)
    assert (proj / "_data" / "df1.parquet") in inputs


# ---------------------------------------------------------------------------
# 9. formats._csv nonexistent Boolean override gives helpful missing-column error
# ---------------------------------------------------------------------------
def test_formats_csv_nonexistent_boolean_override_error(tmp_path):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has no column"):
        formats.scan(csv_path, "csv", {"schema_overrides": {"typo": "Boolean"}})


# ---------------------------------------------------------------------------
# 10. manifest: notebooks missing path, broken symlink, non-string chart.dataframe
# ---------------------------------------------------------------------------
def test_manifest_edge_cases(tmp_path):
    # Notebook omitting path and name
    p1 = _init_pipeline(tmp_path / "nb_proj", pid="acme/nb", extra_toml="\n[notebooks.nb1]\n")
    loaded = manifest.load_manifest(p1)
    assert "nb1" in loaded["notebooks"]

    # Broken symlink in src/
    src_dir = p1 / "src"
    src_dir.mkdir()
    os.symlink(tmp_path / "nonexistent_target", src_dir / "broken.py")
    loaded2 = manifest.load_manifest(p1)
    assert loaded2["project"]["id"] == "acme/nb"

    # Non-string charts.<id>.dataframe raises ValueError (not TypeError)
    p2 = _init_pipeline(
        tmp_path / "bad_chart",
        pid="acme/bad",
        extra_toml='\n[charts.c1]\ndocs = "hi"\ndataframe = ["df1"]\n',
    )
    with pytest.raises(ValueError, match="must be a string"):
        manifest.load_manifest(p2)

    # Non-string series.docs_path raises ValueError
    p3 = _init_pipeline(
        tmp_path / "bad_series",
        pid="acme/bads",
        extra_toml='\n[dataframes.df1.series.x]\ndocs_path = 123\n',
    )
    with pytest.raises(ValueError, match="docs_path"):
        manifest.load_manifest(p3)


# ---------------------------------------------------------------------------
# 11. publish.py prevents path traversal and SameFileError; CLI --project-dir
# ---------------------------------------------------------------------------
def test_publish_plan_constrains_outside_and_absolute_paths(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared_file = shared / "ext.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(shared_file)

    proj = _init_pipeline(
        tmp_path / "proj",
        pid="acme/pub",
        extra_toml=f'\n[dataframes.ext]\npath = "../shared/ext.parquet"\ndocs = "ext"\n'
        f'[dataframes.absdf]\npath = "{shared_file.as_posix()}"\ndocs = "abs"\n',
    )
    loaded = manifest.load_manifest(proj)
    pub_dir = tmp_path / "out" / "acme/pub"
    plan = publish.get_pipeline_publishing_plan(loaded, pub_dir)
    for src, dest in plan.items():
        assert dest.resolve().is_relative_to(pub_dir.resolve()), f"{dest} escaped {pub_dir}"
        assert dest.resolve() != src.resolve()


def test_cli_publish_default_dir_uses_project_dir(tmp_path, monkeypatch):
    proj = _init_pipeline(tmp_path / "my_proj", pid="acme/pubcli")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    res = CliRunner().invoke(main, ["publish", "--project-dir", str(proj)])
    assert res.exit_code == 0, res.output
    assert (proj / "_output" / "to_be_published" / "chartbook.toml").is_file()
    assert not (elsewhere / "_output").exists()


# ---------------------------------------------------------------------------
# 12. catalog_config.migrate updates relative [catalog] path in settings.toml
# ---------------------------------------------------------------------------
def test_catalog_migrate_updates_relative_settings_path(tmp_path, monkeypatch):
    cb_home = tmp_path / "cb_home"
    cat_dir = cb_home / "mycat"
    cat_dir.mkdir(parents=True)
    (cat_dir / "README.md").write_text("# Cat\n", encoding="utf-8")
    (cat_dir / "chartbook.toml").write_text(
        '[project]\ntype = "catalog"\nid = "mycat"\nname = "My Cat"\nreadme = "./README.md"\n',
        encoding="utf-8",
    )
    settings_path = cb_home / "settings.toml"
    settings_path.write_text('[catalog]\npath = "mycat/chartbook.toml"\n', encoding="utf-8")
    monkeypatch.setenv("CHARTBOOK_CONFIG_DIR", str(cb_home))
    monkeypatch.setattr(config, "get_global_settings_path", lambda: settings_path)
    monkeypatch.setattr(config, "get_global_catalog_path", lambda: cb_home / "catalog.toml")

    other = tmp_path / "other_cwd"
    other.mkdir()
    monkeypatch.chdir(other)

    target, _ = catalog_config.migrate()
    assert target.name == "catalog.toml"
    updated = config.read_global_settings()
    assert Path(updated["catalog"]["path"]).resolve() == target.resolve()


# ---------------------------------------------------------------------------
# 13. run._stack fallback and non-list JSON; path_validation UNC on WSL
# ---------------------------------------------------------------------------
def test_run_stack_fallback_and_non_list(monkeypatch):
    monkeypatch.setenv(run_mod.RUN_DIR_ENV_VAR, "/tmp/p")
    monkeypatch.setenv(run_mod.RUN_SCRIPT_ENV_VAR, "build")
    monkeypatch.setenv(run_mod.RUN_STACK_ENV_VAR, "")
    assert run_mod.running("/tmp/p", "build") is True

    monkeypatch.setenv(run_mod.RUN_STACK_ENV_VAR, "null")
    assert run_mod._stack() == [("/tmp/p", "build")]


def test_path_validation_unc_reachable_on_wsl():
    env = ShellEnvironment(os_name="Linux", is_wsl=True)
    diags = diagnose_path(r"\\server\share", env)
    assert any("UNC path detected" in d.message for d in diags)


# ---------------------------------------------------------------------------
# 14. plotting fixes
# ---------------------------------------------------------------------------
def test_plotting_fixes(tmp_path):
    # scatter + color_by + regression_line
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 6], "y": [2, 4, 5, 4, 5, 7], "cat": ["a", "a", "a", "b", "b", "b"]})
    r = plotting.scatter(df, x="x", y="y", color_by="cat", regression_line=True)
    assert any(t.name == "Trend" for t in r.figure.data)
    assert any(line.get_label() == "Trend" for line in r.mpl_axes.get_lines())

    # scatter + hlines + regression_line in Matplotlib
    r_hl = plotting.scatter(df, x="x", y="y", hlines=[{"y": 4}], regression_line=True)
    assert any(line.get_label() == "Trend" for line in r_hl.mpl_axes.get_lines())

    # constant size column
    df_const = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6], "s": [10, 10, 10]})
    r_sz = plotting.scatter(df_const, x="x", y="y", size="s")
    assert len(r_sz.figure.data) == 1
    assert len(r_sz.mpl_axes.collections) == 1

    # >10 series and >10 color_by categories
    df_many = pd.DataFrame({"x": [1, 2, 3], **{f"y{i}": [i, i + 1, i + 2] for i in range(12)}})
    r_many = plotting.line(df_many, x="x", y=[f"y{i}" for i in range(12)])
    assert len(r_many.figure.data) == 12
    assert len(r_many.mpl_axes.get_lines()) == 12

    df_cats = pd.DataFrame({"x": list(range(12)), "y": list(range(12)), "c": [f"c{i}" for i in range(12)]})
    r_cats = plotting.scatter(df_cats, x="x", y="y", color_by="c")
    assert len(r_cats.figure.data) == 12

    # vlines label preserved when source/caption is set
    r_ann = plotting.line(df, x="x", y="y", vlines=[{"x": 3, "label": "Event"}], source="FRED")
    texts = [a.text for a in r_ann.figure.layout.annotations]
    assert "Event" in texts and any("FRED" in t for t in texts)

    # dual axis annotations & bar+line datetime xlim
    df_dt = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=6, freq="ME"),
        "gdp": [100, 102, 104, 103, 105, 108],
        "rate": [0.01, 0.02, 0.015, 0.025, 0.03, 0.02],
    })
    r_dual = plotting.dual(
        df_dt, x="date", left_y="gdp", right_y="rate",
        left_type="bar", right_type="line",
        caption="Cap", note="Note", source="Src",
    )
    assert len(r_dual.figure.layout.annotations) == 3
    xmin, xmax = r_dual.mpl_axes.get_xlim()
    assert -2 < xmin < 2 and 4 < xmax < 8

    # area with rgba color
    r_area = plotting.area(df, x="x", y="y", color="rgba(255, 0, 0, 0.8)")
    assert r_area.figure.data[0].fillcolor == "rgba(255, 0, 0, 0.8)"

    # unique div_id in _repr_html_
    assert r_area._repr_html_() != r_area._repr_html_()

    # save() preserves mpl_axes customizations
    r_custom = plotting.line(df, x="x", y="y")
    r_custom.mpl_axes.set_title("Custom Title Preserved")
    r_custom.save("custom", output_dir=tmp_path)
    assert r_custom.png_path.is_file()
    assert r_custom.mpl_axes.get_title() == "Custom Title Preserved"


# ---------------------------------------------------------------------------
# 15. utils, create_data_glimpses, diagnostics link
# ---------------------------------------------------------------------------
def test_empty_and_single_column_dataframes_and_diagnostics_link(tmp_path):
    one_col = tmp_path / "one.parquet"
    pl.DataFrame({"date": ["2024-01-01", "2024-01-02"]}).write_parquet(one_col)
    assert utils.most_recent_valid_datapoints(one_col, date_col="date") == ("N/A", "N/A")

    empty_col = tmp_path / "empty.parquet"
    pl.DataFrame().write_parquet(empty_col)
    rep = create_data_glimpses.get_dataset_report(empty_col)
    assert rep.get("error") is None
    assert rep["n_cols"] == 0

    assert diagnostics._build_page_link("pipeline", "acme/p", "acme/p") == "./pipelines/acme--p_README.html"
